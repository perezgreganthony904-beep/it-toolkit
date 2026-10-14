"""
IT Support Automation Toolkit


Uses Python's standard library. Designed for Windows 10/11.
Run with: python main.py
"""

import csv
import ctypes
from datetime import date, datetime
import getpass
import json
import logging
import platform
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import tkinter as tk
import time
from tkinter import messagebox, ttk
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

BASE_DIR = Path(__file__).resolve().parent
REPORT_DIR = BASE_DIR / "reports"
LOG_DIR = BASE_DIR / "logs"
REPORT_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)
APPROVED_RESTART_SERVICES = {"Spooler": "Print Spooler"}

logging.basicConfig(
    filename=LOG_DIR / "toolkit.log",
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


def run_command(command, timeout=8):
    """Run a command safely and return its output, or a readable error."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
            errors="replace",
        )
        output = (result.stdout or "").strip()
        error = (result.stderr or "").strip()
        return result.returncode, output or error or "(No output returned.)"
    except subprocess.TimeoutExpired:
        logging.warning("Command timed out: %s", command)
        return 124, "The command timed out."
    except (OSError, ValueError) as exc:
        logging.exception("Could not run command: %s", command)
        return 1, f"Could not run command: {exc}"


def system_information():
    """Collect basic, non-secret workstation information."""
    info = {
        "Computer name": platform.node(),
        "Operating system": platform.platform(),
        "OS version": platform.version(),
        "Architecture": platform.machine(),
        "Current user": getpass.getuser(),
        "Python version": platform.python_version(),
    }
    return info


def system_information_result():
    return _result(
        "System information",
        "INFO",
        "\n".join(f"{key}: {value}" for key, value in system_information().items()),
        "Confirm this is the intended workstation before attaching the report to a ticket.",
    )


def get_default_gateway():
    """Read the default gateway using Windows PowerShell."""
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' "
        "| Sort-Object RouteMetric "
        "| Select-Object -First 1 -ExpandProperty NextHop)",
    ]
    code, output = run_command(command, timeout=8)
    if code == 0 and output and output != "(No output returned.)":
        first_line = output.splitlines()[0].strip()
        if first_line and first_line.lower() not in {"null", "0.0.0.0"}:
            return first_line
    return None


def ping_host(host):
    """Ping a host once on Windows; return status and command output."""
    code, output = run_command(["ping", "-n", "1", "-w", "2500", host], timeout=5)
    return code == 0, output


def https_connectivity_check(url="https://example.com", timeout=8):
    """Check that an HTTPS server can be reached and returns an HTTP response."""
    try:
        normalized_url = url.strip()
        parsed_url = urlsplit(normalized_url)
    except (AttributeError, ValueError):
        normalized_url = ""
        parsed_url = None
    if not parsed_url or parsed_url.scheme.lower() != "https" or not parsed_url.netloc:
        return {
            "name": f"HTTPS connectivity ({url})",
            "status": "FAIL",
            "details": "Enter a valid URL beginning with https://.",
            "recommendation": "Provide a complete HTTPS URL, such as https://example.com.",
        }

    request = Request(normalized_url, headers={"User-Agent": "ITSupportAutomationToolkit/1.0"}, method="HEAD")
    try:
        with urlopen(request, timeout=timeout) as response:
            status_code = response.status
        details = f"HTTPS connection succeeded; server returned HTTP {status_code}."
        status = "PASS"
    except HTTPError as exc:
        # An HTTP error still proves DNS, TCP, and TLS reached the HTTPS server.
        try:
            details = f"HTTPS connection succeeded; server returned HTTP {exc.code}."
            status = "PASS"
        finally:
            exc.close()
    except (URLError, OSError, ValueError) as exc:
        details = str(exc)
        status = "FAIL"

    return {
        "name": f"HTTPS connectivity ({normalized_url})",
        "status": status,
        "details": details,
        "recommendation": (
            "The HTTPS service responded. Review its HTTP status if the application is still unavailable."
            if status == "PASS"
            else "Check the URL, DNS, network path, and TLS configuration, then retry."
        ),
    }


def network_diagnostics(https_url="https://example.com"):
    """Check gateway, external IP reachability, DNS, HTTPS, and IP configuration."""
    results = []

    gateway = get_default_gateway()
    if gateway:
        ok, output = ping_host(gateway)
        results.append({
            "name": f"Default gateway ({gateway})",
            "status": "PASS" if ok else "FAIL",
            "details": output,
            "recommendation": (
                "Gateway responded." if ok
                else "Check Wi-Fi/Ethernet connection, adapter status, and gateway configuration."
            ),
        })
    else:
        results.append({
            "name": "Default gateway discovery",
            "status": "WARN",
            "details": "Could not automatically identify the IPv4 default gateway.",
            "recommendation": "Review ipconfig /all and confirm the active adapter has a gateway.",
        })

    ok, output = ping_host("1.1.1.1")
    results.append({
        "name": "External IP reachability (1.1.1.1)",
        "status": "PASS" if ok else "FAIL",
        "details": output,
        "recommendation": (
            "External IP responded." if ok
            else "Check gateway reachability and upstream connectivity. Some networks block ICMP, so confirm with another test."
        ),
    })

    try:
        resolved_ip = socket.gethostbyname("example.com")
        results.append({
            "name": "DNS resolution (example.com)",
            "status": "PASS",
            "details": f"example.com resolved to {resolved_ip}",
            "recommendation": "DNS resolution succeeded.",
        })
    except socket.gaierror as exc:
        logging.warning("DNS resolution failed: %s", exc)
        results.append({
            "name": "DNS resolution (example.com)",
            "status": "FAIL",
            "details": str(exc),
            "recommendation": "Check DNS server settings and retry. Compare with nslookup example.com.",
        })

    results.append(https_connectivity_check(https_url))

    # Include adapter configuration for technician review.
    code, output = run_command(["ipconfig", "/all"], timeout=8)
    results.append({
        "name": "IP configuration (ipconfig /all)",
        "status": "INFO" if code == 0 else "WARN",
        "details": output,
        "recommendation": "Review active adapter, IPv4 address, subnet mask, DHCP, gateway, and DNS servers.",
    })
    return results


def disk_space_check(drive="C:\\", warning_percent=15):
    """Check free disk space and flag low space."""
    try:
        usage = shutil.disk_usage(drive)
        total_gb = usage.total / (1024 ** 3)
        free_gb = usage.free / (1024 ** 3)
        free_percent = (usage.free / usage.total) * 100 if usage.total else 0
        status = "WARN" if free_percent < warning_percent else "PASS"
        details = (
            f"Drive: {drive}\n"
            f"Total: {total_gb:.2f} GB\n"
            f"Free: {free_gb:.2f} GB ({free_percent:.1f}%)"
        )
        recommendation = (
            f"Free space is below {warning_percent}%. Review temporary files and approved cleanup options."
            if status == "WARN" else "Disk free-space level is above the warning threshold."
        )
        return {
            "name": f"Disk space ({drive})",
            "status": status,
            "details": details,
            "recommendation": recommendation,
        }
    except OSError as exc:
        logging.exception("Disk check failed for %s", drive)
        return {
            "name": f"Disk space ({drive})",
            "status": "FAIL",
            "details": str(exc),
            "recommendation": "Confirm the drive exists and is accessible.",
        }


def _result(name, status, details, recommendation):
    return {
        "name": name,
        "status": status,
        "details": details,
        "recommendation": recommendation,
    }


def is_running_as_admin():
    """Return whether this process has an elevated Windows token."""
    if platform.system() != "Windows":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def system_health_checks():
    """Check uptime and memory use through Windows system information."""
    if platform.system() != "Windows":
        return [_result(
            "System health",
            "WARN",
            "Uptime and memory checks require Windows PowerShell.",
            "Run this check on a supported Windows workstation.",
        )]

    command = [
        "powershell", "-NoProfile", "-Command",
        "$os=Get-CimInstance Win32_OperatingSystem; "
        "$up=(Get-Date)-$os.LastBootUpTime; "
        "[pscustomobject]@{Uptime=$up.ToString(); "
        "TotalMemoryMB=[math]::Round($os.TotalVisibleMemorySize/1024,0); "
        "FreeMemoryMB=[math]::Round($os.FreePhysicalMemory/1024,0)} "
        "| ConvertTo-Json -Compress",
    ]
    code, output = run_command(command, timeout=15)
    if code != 0:
        return [_result("System health", "WARN", output, "Check Windows Management Instrumentation and retry.")]
    try:
        metrics = json.loads(output)
        total_mb = float(metrics["TotalMemoryMB"])
        free_mb = float(metrics["FreeMemoryMB"])
        free_percent = (free_mb / total_mb) * 100 if total_mb else 0
        status = "WARN" if free_percent < 10 else "PASS"
        details = (
            f"Uptime: {metrics['Uptime']}\n"
            f"Memory: {free_mb:.0f} MB free of {total_mb:.0f} MB ({free_percent:.1f}% free)"
        )
        recommendation = (
            "Memory is low; review resource-heavy applications and confirm before closing anything."
            if status == "WARN" else "Uptime and available memory are within the basic check threshold."
        )
        return [_result("System health", status, details, recommendation)]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return [_result("System health", "WARN", f"Could not parse Windows metrics: {exc}\n{output}", "Review PowerShell output.")]


def flush_dns_cache():
    """Flush the local DNS resolver cache; requires administrator privileges."""
    if not is_running_as_admin():
        return _result("Flush DNS cache", "WARN", "Administrator privileges are required.", "Restart the toolkit as administrator, then confirm this action.")
    code, output = run_command(["ipconfig", "/flushdns"], timeout=10)
    return _result(
        "Flush DNS cache", "PASS" if code == 0 else "FAIL", output,
        "Retry the affected hostname lookup." if code == 0 else "Review the command output and Windows DNS Client service.",
    )


def renew_dhcp(adapter=""):
    """Renew a DHCP lease, optionally for one named adapter; requires elevation."""
    if not is_running_as_admin():
        return _result("Renew DHCP lease", "WARN", "Administrator privileges are required.", "Restart the toolkit as administrator, then confirm this action.")
    command = ["ipconfig", "/renew"]
    if adapter.strip():
        command.append(adapter.strip())
    code, output = run_command(command, timeout=45)
    return _result(
        "Renew DHCP lease", "PASS" if code == 0 else "FAIL", output,
        "Verify the adapter received a valid address and gateway." if code == 0 else "Check the DHCP server and adapter connection.",
    )


def clean_approved_temp_files(days_old=7):
    """Remove only non-directory, non-symlink temp files older than the retention period."""
    temp_root = Path(tempfile.gettempdir()).resolve()
    cutoff = time.time() - (days_old * 24 * 60 * 60)
    removed_count = 0
    removed_bytes = 0
    failures = []
    try:
        for item in temp_root.iterdir():
            try:
                if item.is_symlink() or not item.is_file():
                    continue
                file_stat = item.stat()
                if file_stat.st_mtime >= cutoff:
                    continue
                item.unlink()
                removed_count += 1
                removed_bytes += file_stat.st_size
            except OSError as exc:
                failures.append(f"{item.name}: {exc}")
    except OSError as exc:
        return _result("Approved temporary-file cleanup", "FAIL", str(exc), "Check access to the current user's temporary folder.")

    details = f"Removed {removed_count} file(s), freeing {removed_bytes / (1024 ** 2):.1f} MB from {temp_root}."
    if failures:
        details += "\nSkipped: " + "; ".join(failures[:10])
    return _result(
        "Approved temporary-file cleanup", "WARN" if failures else "PASS", details,
        "Review the cleanup result; directories and files newer than seven days were left untouched.",
    )


def restart_approved_service(service_name):
    """Restart a single allowlisted Windows service; requires administrator privileges."""
    if service_name not in APPROVED_RESTART_SERVICES:
        return _result("Restart Windows service", "FAIL", "That service is not on the approved restart list.", "Select an approved service or use L2 service analysis.")
    if not is_running_as_admin():
        return _result("Restart Windows service", "WARN", "Administrator privileges are required.", "Restart the toolkit as administrator, then confirm this action.")
    escaped_name = service_name.replace("'", "''")
    command = [
        "powershell", "-NoProfile", "-Command",
        f"Restart-Service -Name '{escaped_name}' -ErrorAction Stop; "
        f"Get-Service -Name '{escaped_name}' | Select-Object Name,Status | ConvertTo-Json -Compress",
    ]
    code, output = run_command(command, timeout=30)
    return _result(
        f"Restart service ({APPROVED_RESTART_SERVICES[service_name]})",
        "PASS" if code == 0 else "FAIL", output,
        "Verify the service is running and confirm the user's issue is resolved." if code == 0 else "Review service dependencies and related System events before retrying.",
    )


def _valid_network_target(host):
    return isinstance(host, str) and re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host.strip()) is not None


def advanced_network_diagnostics(host="example.com", port=443):
    """Collect traceroute, route, adapter, DNS, and TCP connectivity evidence."""
    host = host.strip() if isinstance(host, str) else ""
    try:
        port = int(port)
    except (TypeError, ValueError):
        port = 0
    if not _valid_network_target(host) or not 1 <= port <= 65535:
        return [_result("Advanced network diagnostics", "FAIL", "Enter a hostname or IPv4 address and a TCP port from 1 to 65535.", "Correct the host and port, then retry.")]

    if platform.system() != "Windows":
        return [_result("Advanced network diagnostics", "WARN", "Traceroute, route table, and adapter checks require Windows.", "Run these checks on Windows.")]

    checks = []
    for name, command, timeout in (
        (f"Traceroute ({host})", ["tracert", "-d", "-h", "12", "-w", "1000", host], 20),
        ("IPv4 route table", ["route", "print", "-4"], 10),
        ("Adapter configuration", ["ipconfig", "/all"], 10),
    ):
        code, output = run_command(command, timeout=timeout)
        checks.append(_result(name, "INFO" if code == 0 else "WARN", output, "Review this evidence alongside the user's scope and symptoms."))

    try:
        resolved = sorted({entry[4][0] for entry in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)})
        checks.append(_result(f"System DNS ({host})", "PASS", ", ".join(resolved), "Compare these addresses with the configured DNS resolver."))
    except socket.gaierror as exc:
        resolved = []
        checks.append(_result(f"System DNS ({host})", "FAIL", str(exc), "Check DNS server configuration and compare with Resolve-DnsName."))

    resolver_command = [
        "powershell", "-NoProfile", "-Command",
        f"Resolve-DnsName -Name '{host}' -Type A -ErrorAction Stop "
        "| Select-Object -ExpandProperty IPAddress -Unique",
    ]
    dns_code, dns_output = run_command(resolver_command, timeout=12)
    resolver_status = "INFO" if dns_code == 0 else "WARN"
    checks.append(_result(f"Configured DNS resolver ({host})", resolver_status, dns_output, "Compare results with system DNS for inconsistencies."))

    try:
        with socket.create_connection((host, port), timeout=5):
            tcp_status, tcp_details = "PASS", f"TCP connection to {host}:{port} succeeded."
    except OSError as exc:
        tcp_status, tcp_details = "FAIL", str(exc)
    checks.append(_result(f"TCP port test ({host}:{port})", tcp_status, tcp_details, "Check routing, firewall policy, service availability, and the target port."))
    return checks


def inspect_windows_service(service_name="Spooler"):
    """Inspect a service's state, startup configuration, and dependencies."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", service_name or ""):
        return _result("Windows service inspection", "FAIL", "Enter a valid Windows service name.", "Use the service name, not a display name with spaces.")
    if platform.system() != "Windows":
        return _result("Windows service inspection", "WARN", "This check requires Windows PowerShell.", "Run on a Windows workstation.")

    command = [
        "powershell", "-NoProfile", "-Command",
        f"$s=Get-CimInstance Win32_Service -Filter \"Name='{service_name}'\"; "
        "if($s){$s | Select-Object Name,DisplayName,State,StartMode,StartName,PathName,"
        "ExitCode,ProcessId,Dependencies | ConvertTo-Json -Compress}else{exit 3}",
    ]
    code, output = run_command(command, timeout=15)
    status = "INFO" if code == 0 else "WARN"
    return _result(
        f"Windows service ({service_name})", status, output,
        "Review state, startup type, dependencies, and binary path before proposing any change.",
    )


def inspect_service_events(days=7, limit=30):
    """Collect recent Service Control Manager events from the System log."""
    if platform.system() != "Windows":
        return _result("Service Control Manager events", "WARN", "This check requires Windows PowerShell.", "Run on a Windows workstation.")
    days = max(1, min(int(days), 30))
    limit = max(1, min(int(limit), 100))
    command = [
        "powershell", "-NoProfile", "-Command",
        f"Get-WinEvent -FilterHashtable @{{LogName='System'; ProviderName='Service Control Manager'; "
        f"StartTime=(Get-Date).AddDays(-{days})}} -MaxEvents {limit} -ErrorAction SilentlyContinue "
        "| Select-Object TimeCreated,Id,LevelDisplayName,Message | ConvertTo-Json -Compress",
    ]
    code, output = run_command(command, timeout=20)
    return _result(
        "Service Control Manager events", "INFO" if code == 0 else "WARN", output,
        "Correlate event IDs and timestamps with the reported service failure; review before remediation.",
    )


def run_integrity_scan(scan_type):
    """Run non-repairing DISM or SFC verification scans with output capture."""
    scan_commands = {
        "DISM": (["DISM.exe", "/Online", "/Cleanup-Image", "/ScanHealth"], 1800),
        "SFC": (["sfc.exe", "/verifyonly"], 1800),
    }
    if scan_type not in scan_commands:
        return _result("System integrity scan", "FAIL", "Choose DISM or SFC.", "Select a supported scan.")
    if platform.system() != "Windows":
        return _result(f"{scan_type} scan", "WARN", "This scan requires Windows.", "Run on a Windows workstation.")
    if not is_running_as_admin():
        return _result(f"{scan_type} scan", "WARN", "Administrator privileges are required; no scan was started.", "Relaunch the toolkit as administrator and explicitly confirm the scan.")
    command, timeout = scan_commands[scan_type]
    code, output = run_command(command, timeout=timeout)
    normalized_output = output.lower()
    findings_present = any(phrase in normalized_output for phrase in (
        "component store is repairable",
        "integrity violations found",
        "found integrity violations",
        "found corrupt files",
        "corruption was detected",
    ))
    status = "FAIL" if code != 0 else "WARN" if findings_present else "PASS"
    return _result(
        f"{scan_type} system integrity scan", status,
        f"Exit code: {code}\n{output}",
        "Review detected integrity findings and follow your organization's approved repair procedure. This scan does not repair files."
        if findings_present else "Review the complete scan output. This verification scan does not repair files or the component store.",
    )


def validate_employee_record(record):
    """Validate required onboarding data without storing credentials or secrets."""
    required_fields = ("employee_id", "full_name", "work_email", "department", "manager", "start_date")
    errors = [f"{field.replace('_', ' ').title()} is required." for field in required_fields if not record.get(field, "").strip()]
    employee_id = record.get("employee_id", "").strip()
    if employee_id and not re.fullmatch(r"[A-Za-z0-9._-]{2,40}", employee_id):
        errors.append("Employee ID may contain only letters, numbers, periods, underscores, and hyphens.")
    email = record.get("work_email", "").strip()
    if email and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        errors.append("Work email does not have a valid basic email format.")
    start_date = record.get("start_date", "").strip()
    if start_date:
        try:
            date.fromisoformat(start_date)
        except ValueError:
            errors.append("Start date must use YYYY-MM-DD format.")
    return errors


def onboarding_checklist(record):
    """Create a first-day checklist from validated employee information."""
    return [
        f"Confirm manager approval and start date for {record.get('full_name', '').strip()}.",
        f"Verify the requested work email and department: {record.get('work_email', '').strip()} / {record.get('department', '').strip()}.",
        "Provision only approved accounts, groups, and licenses; never request or record a password.",
        "Prepare an assigned workstation and verify asset ownership and security enrollment.",
        "Confirm MFA enrollment and provide approved sign-in and support instructions.",
        "Record completion and unresolved access issues in the associated support ticket.",
    ]


def save_l2_escalation_report(results, ticket_info=None, actions_attempted="", unresolved_symptoms=""):
    """Save a focused L2 escalation report with unresolved symptoms and attempted actions."""
    ticket_info = ticket_info or {}
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_ticket_id = re.sub(r"[^A-Za-z0-9_-]+", "_", ticket_info.get("ticket_id", "")).strip("_")[:50]
    ticket_suffix = f"_{safe_ticket_id}" if safe_ticket_id else ""
    report_path = REPORT_DIR / f"l2_escalation_{timestamp}{ticket_suffix}.txt"
    content = [
        "L2 ESCALATION REPORT",
        "=" * 60,
        f"Actions attempted:\n{actions_attempted.strip() or 'Not provided'}",
        "",
        f"Unresolved symptoms:\n{unresolved_symptoms.strip() or 'Not provided'}",
        "",
        format_report(results, ticket_info),
    ]
    report_path.write_text("\n".join(content), encoding="utf-8")
    logging.info("L2 escalation report saved: %s", report_path.name)
    return report_path


def collect_results(https_url="https://example.com"):
    """Run all diagnostic modules and assemble a report."""
    logging.info("Full diagnostic started")
    results = []

    results.append(system_information_result())
    results.extend(system_health_checks())
    results.extend(network_diagnostics(https_url))
    results.append(disk_space_check())

    logging.info("Full diagnostic completed with %d checks", len(results))
    return results


def build_triage_plan(results, ticket_info=None):
    """Suggest a support tier and return category-specific troubleshooting steps."""
    ticket_info = ticket_info or {}
    category = ticket_info.get("category", "Other")
    playbooks = {
        "Connectivity": {
            "L1": [
                "Confirm whether one user, one device, or multiple users are affected.",
                "Check Wi-Fi or Ethernet, airplane mode, VPN state, and the reported URL.",
                "Reconnect the network and retry; compare with another approved site or device.",
            ],
            "L2": [
                "Compare gateway, external IP, DNS, and HTTPS results to isolate the failing layer.",
                "Review ipconfig /all for adapter, DHCP, gateway, DNS, and proxy configuration.",
                "Check system time, certificate errors, VPN routes, and approved proxy settings.",
            ],
            "L3": [
                "Escalate multi-user or persistent outages to the network/security service owner.",
                "Provide sanitized diagnostics for review of DNS, DHCP, routing, firewall, proxy, or TLS infrastructure.",
            ],
        },
        "Hardware": {
            "L1": [
                "Confirm the affected device and symptom; check power, cables, and indicator lights.",
                "Reconnect the peripheral or try an approved known-good cable or port.",
            ],
            "L2": [
                "Review Device Manager and system event logs for device or driver errors.",
                "Compare with a known-good accessory and record model, serial number, and error codes.",
            ],
            "L3": [
                "Escalate suspected component failure for engineering or vendor diagnosis.",
                "Attach device identifiers, event evidence, warranty details, and steps already attempted.",
            ],
        },
        "Software": {
            "L1": [
                "Capture the exact error and determine whether one user or multiple users are affected.",
                "Close and reopen the application; verify sign-in, network access, and available updates.",
            ],
            "L2": [
                "Review application and Windows event logs, version, dependencies, and recent changes.",
                "Reproduce with an approved test account or profile; use repair actions only if authorized.",
            ],
            "L3": [
                "Escalate repeatable defects or broad impact to the application owner or vendor.",
                "Provide sanitized logs, version/build, reproduction steps, and impact scope.",
            ],
        },
        "Account access": {
            "L1": [
                "Verify the user identity and affected service; check for account lockout or MFA prompts.",
                "Confirm the user is using the correct sign-in method; never request or record a password.",
            ],
            "L2": [
                "Check account status, group/role assignment, directory synchronization, and sign-in logs.",
                "Compare the failure with another authorized account and note the exact error or correlation ID.",
            ],
            "L3": [
                "Escalate suspected identity-provider, SSO, conditional-access, or directory-wide failures.",
                "Include timestamps, correlation IDs, affected scope, and sanitized sign-in evidence.",
            ],
        },
        "Other": {
            "L1": [
                "Clarify the expected behavior, exact symptom, start time, and affected users or devices.",
                "Try a safe, reversible retry and record the exact result; do not change configuration without approval.",
            ],
            "L2": [
                "Gather relevant logs, versions, recent changes, and a repeatable set of steps.",
                "Compare with a known-good user or device to narrow the responsible component.",
            ],
            "L3": [
                "Route unresolved or broad-impact issues to the owning specialist team or vendor.",
                "Attach sanitized evidence, business impact, scope, and all troubleshooting already completed.",
            ],
        },
    }
    category = category if category in playbooks else "Other"

    failures = [item for item in results if item.get("status") == "FAIL"]
    warnings = [item for item in results if item.get("status") == "WARN"]
    if len(failures) >= 2:
        automatic_tier = "L2"
        reason = f"{len(failures)} checks failed; investigate the underlying technical cause."
    elif failures:
        automatic_tier = "L1"
        reason = "One check failed; begin with first-line validation, then escalate if it persists."
    elif warnings:
        automatic_tier = "L1"
        reason = "No checks failed, but warnings need first-line review."
    else:
        automatic_tier = "L1"
        reason = "No checks failed; complete first-line verification with the user."

    requested_tier = ticket_info.get("support_tier", "Auto")
    selected_tier = requested_tier if requested_tier in {"L1", "L2", "L3"} else automatic_tier
    if selected_tier != automatic_tier:
        reason = f"{selected_tier} selected by technician; automatic suggestion was {automatic_tier}. {reason}"

    return {
        "category": category,
        "recommended_tier": selected_tier,
        "automatic_tier": automatic_tier,
        "reason": reason,
        "playbooks": playbooks[category],
    }


def format_report(results, ticket_info=None):
    """Format collected results as readable plain text."""
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    lines = [
        "IT SUPPORT AUTOMATION TOOLKIT",
        "Automated Diagnostic Report",
        "=" * 60,
        f"Generated: {now}",
        f"Computer: {platform.node()}",
        "",
    ]
    if ticket_info:
        lines.extend([
            f"Ticket ID: {ticket_info.get('ticket_id', '') or 'Not provided'}",
            f"Issue category: {ticket_info.get('category', '') or 'Not provided'}",
            f"Support tier: {ticket_info.get('support_tier', 'Auto') or 'Auto'}",
            f"Technician notes: {ticket_info.get('notes', '') or 'None'}",
            "",
        ])
    lines.extend([
        "NOTE: Results are indicators, not a definitive diagnosis. ICMP may be blocked.",
        "",
    ])
    triage = build_triage_plan(results, ticket_info)
    lines.extend([
        "SUPPORT TRIAGE",
        "-" * 60,
        f"Suggested tier: {triage['recommended_tier']} (automatic: {triage['automatic_tier']})",
        f"Reason: {triage['reason']}",
        f"Category playbook: {triage['category']}",
    ])
    for tier, actions in triage["playbooks"].items():
        lines.append(f"{tier} steps:")
        lines.extend(f"- {action}" for action in actions)
    lines.append("")
    for index, item in enumerate(results, start=1):
        lines.extend([
            f"{index}. {item['name']} [{item['status']}]",
            "-" * 60,
            item["details"],
            f"Recommended next step: {item['recommendation']}",
            "",
        ])
    counts = {}
    for item in results:
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    lines.extend(["SUMMARY", "-" * 60])
    lines.extend(f"{status}: {count}" for status, count in sorted(counts.items()))
    lines.append("")
    return "\n".join(lines)


def _report_path(extension, ticket_info=None):
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ticket_id = (ticket_info or {}).get("ticket_id", "")
    safe_ticket_id = re.sub(r"[^A-Za-z0-9_-]+", "_", ticket_id).strip("_")[:50]
    ticket_suffix = f"_{safe_ticket_id}" if safe_ticket_id else ""
    return REPORT_DIR / f"diagnostic_report_{timestamp}{ticket_suffix}.{extension}"


def _report_metadata(ticket_info=None):
    ticket_info = ticket_info or {}
    return {
        "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "computer": platform.node(),
        "ticket_id": ticket_info.get("ticket_id", ""),
        "category": ticket_info.get("category", ""),
        "support_tier": ticket_info.get("support_tier", "Auto"),
        "technician_notes": ticket_info.get("notes", ""),
    }


def save_report(results, ticket_info=None):
    """Save a timestamped text report under the reports folder."""
    report_path = _report_path("txt", ticket_info)
    report_path.write_text(format_report(results, ticket_info), encoding="utf-8")
    logging.info("Report saved: %s", report_path.name)
    return report_path


def save_csv_report(results, ticket_info=None):
    """Save one CSV row per diagnostic check, with ticket metadata on each row."""
    report_path = _report_path("csv", ticket_info)
    metadata = _report_metadata(ticket_info)
    triage = build_triage_plan(results, ticket_info)
    fieldnames = [
        "generated", "computer", "ticket_id", "category", "support_tier",
        "triage_reason", "tier_steps", "technician_notes",
        "check_number", "check", "status", "details", "recommendation",
    ]
    with report_path.open("w", newline="", encoding="utf-8-sig") as report_file:
        writer = csv.DictWriter(report_file, fieldnames=fieldnames)
        writer.writeheader()
        for index, result in enumerate(results, start=1):
            writer.writerow({
                **metadata,
                "triage_reason": triage["reason"],
                "tier_steps": " | ".join(triage["playbooks"][triage["recommended_tier"]]),
                "check_number": index,
                "check": result["name"],
                "status": result["status"],
                "details": result["details"],
                "recommendation": result["recommendation"],
            })
    logging.info("CSV report saved: %s", report_path.name)
    return report_path


def save_json_report(results, ticket_info=None):
    """Save a structured JSON report with ticket metadata and all check results."""
    report_path = _report_path("json", ticket_info)
    report_data = {
        "metadata": _report_metadata(ticket_info),
        "triage": build_triage_plan(results, ticket_info),
        "results": results,
    }
    report_path.write_text(json.dumps(report_data, indent=2, ensure_ascii=False), encoding="utf-8")
    logging.info("JSON report saved: %s", report_path.name)
    return report_path


class ToolkitApp:
    """Tkinter workspace for routine checks, deeper investigation, and ticket work."""

    def __init__(self, root):
        self.root = root
        self.root.title("IT Support Desk Toolkit")
        self.root.geometry("1120x820")
        self.root.minsize(900, 680)
        self.current_results = []
        self.current_ticket = {}
        self.running = False
        self.closing = False
        self.action_buttons = []
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background="#f1f5f4")
        style.configure("TLabel", background="#f1f5f4", foreground="#20332f")
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"), foreground="#173b32")
        style.configure("Subtitle.TLabel", foreground="#526760")
        style.configure("TNotebook", background="#f1f5f4", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(14, 8), font=("Segoe UI", 10, "bold"))
        style.configure("Accent.TButton", padding=(10, 7), foreground="#ffffff", background="#176b55")
        style.map("Accent.TButton", background=[("active", "#105440"), ("disabled", "#93aaa2")])

        container = ttk.Frame(root, padding=14)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=1)
        container.rowconfigure(2, weight=1)

        header = ttk.Frame(container)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(header, text="Support Desk Toolkit", style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text="First-line checks, advanced diagnostics, and ticket-ready reports", style="Subtitle.TLabel").pack(anchor="w", pady=(2, 0))

        ticket_frame = ttk.LabelFrame(container, text="Ticket context", padding=9)
        ticket_frame.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        for column in (1, 3, 5):
            ticket_frame.columnconfigure(column, weight=1)
        ttk.Label(ticket_frame, text="Ticket ID").grid(row=0, column=0, sticky="w", padx=(0, 5), pady=3)
        self.ticket_id = ttk.Entry(ticket_frame)
        self.ticket_id.grid(row=0, column=1, sticky="ew", padx=(0, 12), pady=3)
        ttk.Label(ticket_frame, text="Category").grid(row=0, column=2, sticky="w", padx=(0, 5), pady=3)
        self.category = ttk.Combobox(
            ticket_frame,
            values=("Connectivity", "Hardware", "Software", "Account access", "Other"),
            state="readonly",
        )
        self.category.set("Connectivity")
        self.category.grid(row=0, column=3, sticky="ew", padx=(0, 12), pady=3)
        ttk.Label(ticket_frame, text="Tier").grid(row=0, column=4, sticky="w", padx=(0, 5), pady=3)
        self.support_tier = ttk.Combobox(ticket_frame, values=("Auto", "L1", "L2", "L3"), state="readonly", width=8)
        self.support_tier.set("Auto")
        self.support_tier.grid(row=0, column=5, sticky="ew", pady=3)
        ttk.Label(ticket_frame, text="HTTPS check URL").grid(row=1, column=0, sticky="w", padx=(0, 5), pady=3)
        self.https_url = ttk.Entry(ticket_frame)
        self.https_url.insert(0, "https://example.com")
        self.https_url.grid(row=1, column=1, columnspan=5, sticky="ew", pady=3)
        ttk.Label(ticket_frame, text="Technician notes").grid(row=2, column=0, sticky="nw", padx=(0, 5), pady=3)
        self.notes = tk.Text(ticket_frame, height=2, wrap="word", relief="solid", borderwidth=1)
        self.notes.grid(row=2, column=1, columnspan=5, sticky="ew", pady=3)

        self.notebook = ttk.Notebook(container)
        self.notebook.grid(row=2, column=0, sticky="nsew")
        self.l1_tab = ttk.Frame(self.notebook, padding=14)
        self.l2_tab = ttk.Frame(self.notebook, padding=14)
        self.onboarding_tab = ttk.Frame(self.notebook, padding=14)
        self.results_tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(self.l1_tab, text="L1 · First response")
        self.notebook.add(self.l2_tab, text="L2 · Investigation")
        self.notebook.add(self.onboarding_tab, text="Onboarding & access")
        self.notebook.add(self.results_tab, text="Results & reports")
        self._build_l1_tab()
        self._build_l2_tab()
        self._build_onboarding_tab()
        self._build_results_tab()

        footer = ttk.Frame(container)
        footer.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(footer, text="Export current results:").pack(side="left", padx=(0, 8))
        self.export_buttons = {}
        for label, extension in (("Text", "txt"), ("CSV", "csv"), ("JSON", "json")):
            button = ttk.Button(footer, text=label, command=lambda selected=extension: self.export_report(selected))
            button.pack(side="left", padx=(0, 6))
            button.configure(state="disabled")
            self.export_buttons[extension] = button
        self.status = ttk.Label(footer, text="Ready", anchor="e")
        self.status.pack(side="right", fill="x", expand=True)
        if platform.system() != "Windows":
            self.status.configure(text="Some checks and repairs require Windows.")

    def _section(self, parent, title, row, column=0, columnspan=1):
        section = ttk.LabelFrame(parent, text=title, padding=10)
        section.grid(row=row, column=column, columnspan=columnspan, sticky="nsew", padx=5, pady=5)
        return section

    def _button(self, parent, text, command, row, column=0, columnspan=1, accent=False):
        button = ttk.Button(parent, text=text, command=command, style="Accent.TButton" if accent else "TButton")
        button.grid(row=row, column=column, columnspan=columnspan, sticky="ew", padx=4, pady=4)
        self.action_buttons.append(button)
        return button

    def _build_l1_tab(self):
        self.l1_tab.columnconfigure((0, 1), weight=1)
        checks = self._section(self.l1_tab, "Routine checks", 0, columnspan=2)
        checks.columnconfigure((0, 1), weight=1)
        self._button(checks, "Run full workstation check", lambda: self._run_operation(
            "Full workstation check",
            lambda https_url=self.https_url.get().strip(): collect_results(https_url),
        ), 0, columnspan=2, accent=True)
        self._button(checks, "Network troubleshooting", lambda: self._run_operation(
            "Network troubleshooting",
            lambda https_url=self.https_url.get().strip(): network_diagnostics(https_url),
        ), 1, column=0)
        self._button(checks, "System details, health, and disk", lambda: self._run_operation(
            "System health", lambda: [system_information_result()] + system_health_checks() + [disk_space_check()]
        ), 1, column=1)
        repairs = self._section(self.l1_tab, "Low-risk repairs (confirmation required)", 1, columnspan=2)
        repairs.columnconfigure((0, 1), weight=1)
        self._button(repairs, "Flush DNS cache", lambda: self._run_operation(
            "Flush DNS cache", flush_dns_cache,
            "Flush the local DNS resolver cache? This does not change DNS settings.",
        ), 0, column=0)
        self._button(repairs, "Renew DHCP lease", lambda: self._run_operation(
            "Renew DHCP lease", renew_dhcp,
            "Renew the DHCP lease for all adapters? Network connectivity may briefly interrupt.",
        ), 0, column=1)
        self._button(repairs, "Clean old temporary files", lambda: self._run_operation(
            "Temporary-file cleanup", clean_approved_temp_files,
            "Remove regular files older than 7 days from this user's temporary folder? Folders and newer files are excluded.",
        ), 1, column=0)
        service_frame = ttk.Frame(repairs)
        service_frame.grid(row=1, column=1, sticky="ew", padx=4, pady=4)
        service_frame.columnconfigure(0, weight=1)
        self.restart_service = ttk.Combobox(service_frame, values=tuple(APPROVED_RESTART_SERVICES), state="readonly")
        self.restart_service.set("Spooler")
        self.restart_service.grid(row=0, column=0, sticky="ew", padx=(0, 5))
        service_button = ttk.Button(service_frame, text="Restart approved service", command=self._restart_selected_service)
        service_button.grid(row=0, column=1, sticky="ew")
        self.action_buttons.append(service_button)
        ttk.Label(
            self.l1_tab,
            text="Repairs are limited to the current user's old temp files, DHCP renewal, DNS cache flush, and the approved service list.",
            wraplength=900,
            style="Subtitle.TLabel",
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 0))

    def _build_l2_tab(self):
        self.l2_tab.columnconfigure((0, 1), weight=1)
        network = self._section(self.l2_tab, "Advanced network diagnostics", 0, columnspan=2)
        network.columnconfigure(1, weight=1)
        network.columnconfigure(3, weight=1)
        ttk.Label(network, text="Host").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.advanced_host = ttk.Entry(network)
        self.advanced_host.insert(0, "example.com")
        self.advanced_host.grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        ttk.Label(network, text="TCP port").grid(row=0, column=2, sticky="w", padx=4, pady=4)
        self.advanced_port = ttk.Entry(network, width=8)
        self.advanced_port.insert(0, "443")
        self.advanced_port.grid(row=0, column=3, sticky="ew", padx=4, pady=4)
        self._button(network, "Run traceroute, route, adapter, DNS, and TCP checks", lambda: self._run_operation(
            "Advanced network diagnostics",
            lambda host=self.advanced_host.get(), port=self.advanced_port.get(): advanced_network_diagnostics(host, port),
        ), 1, columnspan=4, accent=True)

        analysis = self._section(self.l2_tab, "Windows service and event analysis", 1, columnspan=2)
        analysis.columnconfigure(1, weight=1)
        ttk.Label(analysis, text="Service name").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.service_name = ttk.Entry(analysis)
        self.service_name.insert(0, "Spooler")
        self.service_name.grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        self._button(analysis, "Inspect service state and dependencies", lambda: self._run_operation(
            "Service inspection", lambda service_name=self.service_name.get().strip(): inspect_windows_service(service_name),
        ), 0, column=2, accent=True)
        self._button(analysis, "Review recent service events", lambda: self._run_operation(
            "Service event analysis", inspect_service_events,
        ), 0, column=3)

        scans = self._section(self.l2_tab, "System integrity scans (administrator required)", 2, columnspan=2)
        scans.columnconfigure((0, 1), weight=1)
        self._button(scans, "DISM component-store scan", lambda: self._run_operation(
            "DISM scan", lambda: run_integrity_scan("DISM"),
            "Run DISM /ScanHealth? It can take several minutes and requires an elevated process. It scans without repairing.",
        ), 0, column=0)
        self._button(scans, "SFC file verification", lambda: self._run_operation(
            "SFC verification", lambda: run_integrity_scan("SFC"),
            "Run SFC /verifyonly? It can take several minutes and requires an elevated process. It verifies without repairing.",
        ), 0, column=1)

        escalation = self._section(self.l2_tab, "Escalation notes", 3, columnspan=2)
        escalation.columnconfigure((0, 1), weight=1)
        ttk.Label(escalation, text="Actions attempted").grid(row=0, column=0, sticky="w", padx=4)
        ttk.Label(escalation, text="Unresolved symptoms and impact").grid(row=0, column=1, sticky="w", padx=4)
        self.actions_attempted = tk.Text(escalation, height=3, wrap="word", relief="solid", borderwidth=1)
        self.actions_attempted.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        self.unresolved_symptoms = tk.Text(escalation, height=3, wrap="word", relief="solid", borderwidth=1)
        self.unresolved_symptoms.grid(row=1, column=1, sticky="nsew", padx=4, pady=4)
        self._button(escalation, "Save L2 escalation report", self.save_escalation_report, 2, columnspan=2, accent=True)

    def _build_onboarding_tab(self):
        self.onboarding_tab.columnconfigure((0, 1), weight=1)
        employee = self._section(self.onboarding_tab, "Employee record", 0, columnspan=2)
        employee.columnconfigure(1, weight=1)
        employee.columnconfigure(3, weight=1)
        self.employee_fields = {}
        labels = (
            ("employee_id", "Employee ID"),
            ("full_name", "Full name"),
            ("work_email", "Work email"),
            ("department", "Department"),
            ("manager", "Manager"),
            ("start_date", "Start date (YYYY-MM-DD)"),
        )
        for index, (key, label) in enumerate(labels):
            row, side = divmod(index, 2)
            label_column = side * 2
            field_column = label_column + 1
            ttk.Label(employee, text=label).grid(row=row, column=label_column, sticky="w", padx=4, pady=4)
            field = ttk.Entry(employee)
            field.grid(row=row, column=field_column, sticky="ew", padx=4, pady=4)
            self.employee_fields[key] = field
        self._button(employee, "Validate employee record", self.validate_employee_form, 3, column=0, accent=True)
        self._button(employee, "Generate onboarding checklist", self.generate_onboarding, 3, column=1)

        access = self._section(self.onboarding_tab, "Account and access troubleshooting note", 1, columnspan=2)
        access.columnconfigure(0, weight=1)
        access.columnconfigure(1, weight=1)
        ttk.Label(access, text="Symptom / exact error").grid(row=0, column=0, sticky="w", padx=4)
        ttk.Label(access, text="Checks already performed").grid(row=0, column=1, sticky="w", padx=4)
        self.access_symptom = tk.Text(access, height=4, wrap="word", relief="solid", borderwidth=1)
        self.access_symptom.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        self.access_attempts = tk.Text(access, height=4, wrap="word", relief="solid", borderwidth=1)
        self.access_attempts.grid(row=1, column=1, sticky="nsew", padx=4, pady=4)
        self._button(access, "Add account note to ticket", self.add_account_note, 2, columnspan=2, accent=True)
        ttk.Label(
            self.onboarding_tab,
            text="Use approved identity and HR systems for provisioning. This checklist does not create accounts or request passwords.",
            wraplength=900,
            style="Subtitle.TLabel",
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 0))

    def _build_results_tab(self):
        self.results_tab.columnconfigure(0, weight=1)
        self.results_tab.rowconfigure(0, weight=1)
        self.results_tab.rowconfigure(1, weight=2)
        self.results_table = ttk.Treeview(self.results_tab, columns=("status", "check"), show="headings", height=8)
        self.results_table.heading("status", text="Status")
        self.results_table.heading("check", text="Check or action")
        self.results_table.column("status", width=90, stretch=False)
        self.results_table.column("check", width=700)
        self.results_table.tag_configure("PASS", foreground="#176b3a")
        self.results_table.tag_configure("FAIL", foreground="#a12622")
        self.results_table.tag_configure("WARN", foreground="#8a5a00")
        self.results_table.grid(row=0, column=0, sticky="nsew", pady=(0, 8))
        viewer_frame = ttk.LabelFrame(self.results_tab, text="Selected report", padding=8)
        viewer_frame.grid(row=1, column=0, sticky="nsew")
        viewer_frame.rowconfigure(0, weight=1)
        viewer_frame.columnconfigure(0, weight=1)
        self.report_viewer = tk.Text(viewer_frame, wrap="word", state="disabled", relief="solid", borderwidth=1)
        viewer_scroll = ttk.Scrollbar(viewer_frame, orient="vertical", command=self.report_viewer.yview)
        self.report_viewer.configure(yscrollcommand=viewer_scroll.set)
        self.report_viewer.grid(row=0, column=0, sticky="nsew")
        viewer_scroll.grid(row=0, column=1, sticky="ns")

    def _ticket_data(self):
        return {
            "ticket_id": self.ticket_id.get().strip(),
            "category": self.category.get().strip(),
            "support_tier": self.support_tier.get().strip(),
            "notes": self.notes.get("1.0", "end").strip(),
        }

    def _run_operation(self, title, operation, confirmation=None):
        if self.running:
            return
        if confirmation and not messagebox.askyesno("Confirm action", confirmation, parent=self.root):
            return
        self.running = True
        self.current_ticket = self._ticket_data()
        self.status.configure(text=f"Running: {title}...")
        for button in self.action_buttons:
            button.configure(state="disabled")

        def collect():
            try:
                results = operation()
                if isinstance(results, dict):
                    results = [results]
                self._post_to_ui(lambda: self._show_results(results))
            except Exception as exc:
                logging.exception("Operation failed: %s", title)
                self._post_to_ui(lambda error=exc: self._finish_error(error))

        threading.Thread(target=collect, daemon=True).start()

    def _post_to_ui(self, callback):
        if self.closing:
            return
        try:
            self.root.after(0, callback)
        except (RuntimeError, tk.TclError):
            self.closing = True

    def _on_close(self):
        self.closing = True
        self.root.destroy()

    def _show_results(self, results):
        self.current_results = results
        self.running = False
        for button in self.action_buttons:
            button.configure(state="normal")
        for item in self.results_table.get_children():
            self.results_table.delete(item)
        for index, result in enumerate(results, start=1):
            self.results_table.insert(
                "", "end", values=(result["status"], f"{index}. {result['name']}"),
                tags=(result["status"],),
            )
        self.report_viewer.configure(state="normal")
        self.report_viewer.delete("1.0", "end")
        self.report_viewer.insert("1.0", format_report(results, self.current_ticket))
        self.report_viewer.configure(state="disabled")
        for button in self.export_buttons.values():
            button.configure(state="normal")
        triage = build_triage_plan(results, self.current_ticket)
        self.status.configure(text=f"{len(results)} result(s) ready. Suggested tier: {triage['recommended_tier']}.")
        self.notebook.select(self.results_tab)

    def _finish_error(self, error):
        self.running = False
        for button in self.action_buttons:
            button.configure(state="normal")
        self.status.configure(text=f"Operation failed: {error}")
        messagebox.showerror("Operation failed", str(error), parent=self.root)

    def _restart_selected_service(self):
        service_name = self.restart_service.get()
        self._run_operation(
            "Restart approved service",
            lambda: restart_approved_service(service_name),
            f"Restart {APPROVED_RESTART_SERVICES.get(service_name, service_name)}? This may interrupt active print jobs.",
        )

    def _employee_record(self):
        return {key: field.get().strip() for key, field in self.employee_fields.items()}

    def validate_employee_form(self):
        record = self._employee_record()
        errors = validate_employee_record(record)
        status = "FAIL" if errors else "PASS"
        details = "\n".join(errors) if errors else "Required onboarding fields and basic formats are valid."
        self._run_operation("Employee record validation", lambda: _result(
            "Employee record validation", status, details,
            "Correct the listed fields before processing the onboarding request." if errors else "Continue with the approved onboarding checklist.",
        ))

    def generate_onboarding(self):
        record = self._employee_record()
        errors = validate_employee_record(record)
        if errors:
            self._run_operation("Onboarding validation", lambda: _result(
                "Onboarding checklist", "FAIL", "\n".join(errors), "Correct the employee record and try again."
            ))
            return
        checklist = onboarding_checklist(record)
        details = "Employee record:\n" + "\n".join(f"{key.replace('_', ' ').title()}: {value}" for key, value in record.items())
        details += "\n\nFirst-day checklist:\n" + "\n".join(f"[ ] {item}" for item in checklist)
        self.category.set("Other")
        self._run_operation("Onboarding checklist", lambda: _result(
            "Onboarding checklist", "INFO", details, "Complete each item in the approved HR and identity systems, then update the ticket."
        ))

    def add_account_note(self):
        symptom = self.access_symptom.get("1.0", "end").strip()
        attempts = self.access_attempts.get("1.0", "end").strip()
        if not symptom:
            messagebox.showwarning("Missing symptom", "Enter the symptom or exact error before adding a note.", parent=self.root)
            return
        note = f"Account/access symptom: {symptom}\nChecks already performed: {attempts or 'None recorded'}"
        existing_notes = self.notes.get("1.0", "end").strip()
        self.notes.delete("1.0", "end")
        self.notes.insert("1.0", f"{existing_notes}\n\n{note}".strip())
        self.category.set("Account access")
        self._run_operation("Account access note", lambda: _result(
            "Account/access troubleshooting note", "INFO", note,
            "Continue with approved identity checks; never collect or include a password.",
        ))

    def save_escalation_report(self):
        if not self.current_results:
            messagebox.showwarning("No results", "Run a diagnostic before creating an escalation report.", parent=self.root)
            return
        try:
            path = save_l2_escalation_report(
                self.current_results,
                self._ticket_data(),
                self.actions_attempted.get("1.0", "end").strip(),
                self.unresolved_symptoms.get("1.0", "end").strip(),
            )
            self.status.configure(text=f"L2 escalation report saved: {path.name}")
            messagebox.showinfo("Escalation report saved", str(path), parent=self.root)
        except OSError as exc:
            logging.exception("Could not save L2 escalation report")
            messagebox.showerror("Export failed", str(exc), parent=self.root)

    def export_report(self, extension):
        if not self.current_results:
            return
        exporters = {"txt": save_report, "csv": save_csv_report, "json": save_json_report}
        try:
            report_path = exporters[extension](self.current_results, self._ticket_data())
            self.status.configure(text=f"Saved: {report_path.name}")
        except OSError as exc:
            logging.exception("Report export failed")
            messagebox.showerror("Export failed", str(exc), parent=self.root)
            self.status.configure(text="Report export failed.")


def main():
    root = tk.Tk()
    ToolkitApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
