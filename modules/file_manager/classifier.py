"""Map a file extension to one category. The file itself is never changed."""

from pathlib import Path

DOCUMENTS = "Documents"
IMAGES = "Images"
VIDEOS = "Videos"
AUDIO = "Audio"
ARCHIVES = "Archives"
INSTALLERS = "Installers"
SPREADSHEETS = "Spreadsheets"
DEVELOPMENT = "Development"
OTHERS = "Others"

CATEGORIES = (
    DOCUMENTS,
    IMAGES,
    VIDEOS,
    AUDIO,
    ARCHIVES,
    INSTALLERS,
    SPREADSHEETS,
    DEVELOPMENT,
    OTHERS,
)

# Archives, installers, and unknown files stay in a single category folder.
FORMAT_SUBFOLDERS = frozenset({
    DOCUMENTS,
    IMAGES,
    VIDEOS,
    AUDIO,
    SPREADSHEETS,
    DEVELOPMENT,
})

_CATEGORY_EXTENSIONS: dict[str, frozenset[str]] = {
    DOCUMENTS: frozenset({
        "pdf", "doc", "docx", "txt", "rtf", "odt", "md", "ppt", "pptx", "tex",
    }),
    IMAGES: frozenset({
        "jpg", "jpeg", "png", "gif", "bmp", "webp", "svg", "ico", "heic", "tif", "tiff",
    }),
    VIDEOS: frozenset({"mp4", "mkv", "avi", "mov", "wmv", "webm", "flv", "m4v"}),
    AUDIO: frozenset({"mp3", "wav", "flac", "aac", "ogg", "m4a", "wma"}),
    ARCHIVES: frozenset({"zip", "rar", "7z", "tar", "gz", "bz2", "xz", "iso"}),
    INSTALLERS: frozenset({"exe", "msi", "msix"}),
    SPREADSHEETS: frozenset({"xls", "xlsx", "csv", "ods"}),
    DEVELOPMENT: frozenset({
        "py", "pyw", "js", "jsx", "ts", "tsx", "json", "html", "css",
        "java", "c", "cpp", "h", "hpp", "cs", "go", "rs", "xml",
        "yml", "yaml", "sql", "sh", "ps1", "toml", "ipynb",
    }),
}

_BY_EXTENSION = {
    extension: category
    for category, extensions in _CATEGORY_EXTENSIONS.items()
    for extension in extensions
}


def file_extension(path: str | Path) -> str:
    """Return the lowercase extension without a dot. A dotfile has none."""
    name = Path(path).name
    if name.startswith(".") and name.count(".") == 1:
        return ""
    return Path(path).suffix.lower().lstrip(".")


def classify_file(path: str | Path) -> str:
    """Classify by extension only. Unknown and missing extensions are Others."""
    extension = file_extension(path)
    if not extension:
        return OTHERS
    return _BY_EXTENSION.get(extension, OTHERS)
