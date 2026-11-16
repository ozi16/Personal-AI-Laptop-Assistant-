"""Safety boundary for local NEXUS actions.

Phase 1 only reads system metrics through psutil and writes its own SQLite
database. Phase 2 may move a file inside the approved folder after an explicit
user confirmation. It still cannot delete files, overwrite files, rename files,
change file contents, follow a link outside the source folder, scan a whole
drive, touch Windows system directories, run a shell, or request administrator
rights.
"""

PHASE_NAME = "phase2"
READ_ONLY_SYSTEM_ACCESS = True
FILE_MOVE_REQUIRES_APPROVAL = True
FORBIDDEN_ACTIONS = (
    "delete_files",
    "overwrite_files",
    "rename_files",
    "change_file_content",
    "kill_processes",
    "edit_registry",
    "change_partitions",
    "change_bitlocker",
    "run_admin_shell",
    "run_shell",
    "move_files_without_approval",
    "follow_reparse_points",
)
