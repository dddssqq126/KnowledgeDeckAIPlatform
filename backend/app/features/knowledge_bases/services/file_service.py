import hashlib
import io

ALLOWED_EXTENSIONS = {
    "txt", "pdf", "cs", "md", "docx", "pptx", "xlsx",
    "py", "html", "css",  # common code formats — treated as UTF-8 text
}

# Office Open XML (.docx, .pptx) and ZIP files all start with the PKZIP
# Local File Header magic. We accept anything starting with PK\x03\x04 at
# the validate_content stage and rely on the parser to fail loudly if the
# zip turns out not to be the OOXML format the extension claims.
_ZIP_MAGIC = b"PK\x03\x04"


class ValidationError(Exception):
    """Raised by validators with a stable string code (e.g. invalid_extension)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def normalize_extension(filename: str) -> str:
    """Return the lowercased extension without leading dot, or "" if none."""
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower()


def validate_extension(filename: str) -> str:
    ext = normalize_extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError("invalid_extension")
    return ext


def validate_content(extension: str, head: bytes) -> None:
    """`head` is the first ~1 KiB of the upload."""
    if extension == "pdf":
        if not head.startswith(b"%PDF"):
            raise ValidationError("invalid_content")
        return
    if extension in ("docx", "pptx", "xlsx"):
        # OOXML containers are PKZIP-wrapped XML. The PK magic alone doesn't
        # prove it's the right kind of OOXML — that's the parser's job to
        # discover and surface as an ingest failure.
        if not head.startswith(_ZIP_MAGIC):
            raise ValidationError("invalid_content")
        return
    # txt / cs / md share the text-likeness rule.
    sample = head[:1024]
    if b"\x00" in sample:
        raise ValidationError("invalid_content")
    try:
        sample.decode("utf-8", errors="strict")
    except UnicodeDecodeError as e:
        raise ValidationError("invalid_content") from e


async def stream_into_buffer(
    upload, max_bytes: int
) -> tuple[bytes, str, int]:
    """Read the multipart upload into memory while enforcing the size cap.

    Returns (data, sha256_hex, size_bytes). Raises ValidationError("file_too_large")
    if the upload exceeds `max_bytes`.
    """
    hasher = hashlib.sha256()
    buf = io.BytesIO()
    total = 0
    chunk_size = 64 * 1024
    while True:
        chunk = await upload.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise ValidationError("file_too_large")
        hasher.update(chunk)
        buf.write(chunk)
    return buf.getvalue(), hasher.hexdigest(), total
