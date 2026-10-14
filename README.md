# IT Support Automation Toolkit

A beginner-friendly Python project that automates common Windows Level 1 IT support checks and creates timestamped reports for help desk tickets.

## Problem

IT support technicians often run several commands manually when diagnosing workstation or connectivity issues. This toolkit brings routine checks, controlled actions, and deeper investigation into a single desktop workspace with ticket-ready reports.

## Features

- Collects basic workstation and OS information.
- Discovers the IPv4 default gateway using PowerShell.
- Tests gateway and external IP reachability with `ping`.
- Checks DNS resolution using Python's socket library.
- Checks whether a configurable HTTPS endpoint responds.
- Captures IP configuration with `ipconfig /all`.
- Checks free disk space and flags low available capacity.
- Checks Windows uptime and available memory, with a low-memory warning.
- Provides confirmed L1 DNS flush, DHCP renewal, seven-day temp-file cleanup, and an allowlisted Print Spooler restart.
- Validates onboarding records and generates a first-day checklist; creates account/access troubleshooting notes without collecting passwords.
- Provides L2 traceroute, route table, adapter, DNS comparison, and TCP port diagnostics.
- Inspects Windows service state, startup mode, dependencies, and recent Service Control Manager events.
- Runs confirmed DISM ScanHealth and SFC verify-only scans with captured output.
- Generates L2 escalation reports with actions attempted and unresolved symptoms.
- Exports timestamped text, CSV, and JSON reports in `reports/`.
- Provides a Tkinter interface with diagnostic status indicators and a report viewer.
- Associates ticket IDs, issue categories, and technician notes with reports.
- Provides category-based L1, L2, and L3 troubleshooting playbooks with an automatic tier suggestion that technicians can override.
- Logs application events and errors to `logs/toolkit.log`.
- Handles command timeouts and common errors.

## Requirements

- Windows 10 or Windows 11
- Python 3.10 or newer recommended
- PowerShell available on the system
- No third-party Python packages required

## Installation and usage

1. Install Python 3 from the official Python website and enable the option to add Python to PATH.
2. Download or clone this repository.
3. Open Command Prompt or PowerShell in the project folder.
4. Launch the graphical interface:

   ```powershell
   python main.py
   ```

5. Enter optional ticket details and technician notes, choose an HTTPS URL, and run a diagnostic. Use the export buttons to save the results as text, CSV, or JSON.

## Project structure

```text
it-support-automation-toolkit/
├── main.py
├── reports/
│   └── .gitkeep
├── tests/
│   └── test_toolkit.py
├── logs/                  # Created automatically at runtime
├── .gitignore
└── README.md
```

## Example workflow

1. A user reports that websites are not loading.
2. The technician runs the network diagnostic.
3. The tool checks the default gateway, external IP reachability, DNS resolution, and IP configuration.
4. The technician reviews the findings and follows the recommended next steps.
5. The technician runs a full diagnostic and attaches the generated report to the support ticket, after reviewing it for sensitive details.

## Testing checklist

- [ ] Start the tool and verify the graphical interface appears.
- [ ] Run each diagnostic button and verify the status table and report viewer update.
- [ ] Export a report in text, CSV, and JSON formats and verify ticket details are included.
- [ ] Test HTTPS with a reachable site and an invalid or unavailable URL.
- [ ] Confirm DHCP renewal, DNS flush, temp cleanup, and service restart prompt before running.
- [ ] Verify unprivileged launches do not start admin-only actions.
- [ ] Validate an employee record and generate an onboarding checklist.
- [ ] Run L2 network and service analysis, then save an escalation report.
- [ ] Run system information and verify the computer name and OS are displayed.
- [ ] Run network diagnostics while connected to the internet.
- [ ] Run network diagnostics with Wi-Fi disconnected and observe how failures are reported.
- [ ] Run the disk-space check and confirm capacity is displayed.
- [ ] Run a full diagnostic and verify a timestamped file appears in `reports/`.
- [ ] Inspect `logs/toolkit.log` after a run.
- [ ] Review report content before sharing it; `ipconfig /all` can include internal network details.

## Limitations

- A failed ping does not always mean the network is down; firewalls and networks may block ICMP.
- A successful DNS lookup does not prove that a website's HTTPS service is available.
- The tool provides indicators and suggested next steps, not a guaranteed root-cause diagnosis.
- Gateway discovery relies on a Windows PowerShell command.
- DHCP renewal, DNS cache flush, approved service restart, temp-file deletion, and integrity scans can affect the workstation. Review each confirmation carefully; admin-only actions require launching the app with administrator privileges.
- Temp cleanup only removes regular files older than seven days from the current user's temp folder; it skips subfolders and symbolic links.
- The only service available for restart is the approved Print Spooler service. L2 analysis is read-only; DISM and SFC use scan/verify-only options and do not repair files.
- The toolkit does not create or modify employee accounts; onboarding actions must be completed in approved HR and identity systems.

## Future improvements

- Add configurable disk warning thresholds.
- Export reports to CSV or JSON.
- Add configurable disk and memory warning thresholds.
- Add a safe configuration file for diagnostic targets.

## Security and privacy

The toolkit does not request or store passwords. The IP configuration report may contain private network information, so review generated reports before uploading or sharing them. Use only on devices you are authorized to troubleshoot.

## Learning outcomes

Python functions, exception handling, subprocess execution, file handling, logging, Windows command-line tools, TCP/IP troubleshooting, DNS, and technical documentation.
