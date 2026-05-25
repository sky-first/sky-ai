"""Document parsing and chunking utilities."""

from typing import List, Dict, Any
from pathlib import Path
import pypdf


def parse_pdf(file_path: str) -> List[Dict[str, Any]]:
    """
    Parse a PDF file and extract text chunks.

    Args:
        file_path: Path to PDF file

    Returns:
        List of text chunks with metadata
    """
    chunks = []

    with open(file_path, "rb") as file:
        pdf_reader = pypdf.PdfReader(file)

        for page_num, page in enumerate(pdf_reader.pages):
            text = page.extract_text()

            # Simple chunking by page (can be improved with semantic chunking)
            chunks.append(
                {"text": text, "page": page_num + 1, "source": file_path, "type": "pdf"}
            )

    return chunks


def parse_csv(file_path: str) -> List[Dict[str, Any]]:
    """
    Parse a CSV file and extract text chunks.

    Args:
        file_path: Path to CSV file

    Returns:
        List of text chunks with metadata
    """
    import csv

    chunks = []

    with open(file_path, "r", encoding="utf-8") as file:
        reader = csv.DictReader(file)

        # Convert each row to a text description
        for row_num, row in enumerate(reader):
            text = ", ".join([f"{k}: {v}" for k, v in row.items()])
            chunks.append(
                {
                    "text": text,
                    "row": row_num + 1,
                    "source": file_path,
                    "type": "csv",
                    "data": row,
                }
            )

    return chunks


def parse_text(file_path: str, chunk_size: int = 1000) -> List[Dict[str, Any]]:
    """
    Parse a text file and chunk it.

    Args:
        file_path: Path to text file
        chunk_size: Size of each chunk in characters

    Returns:
        List of text chunks
    """
    with open(file_path, "r", encoding="utf-8") as file:
        content = file.read()

    chunks = []
    for i in range(0, len(content), chunk_size):
        chunk_text = content[i : i + chunk_size]
        chunks.append(
            {"text": chunk_text, "offset": i, "source": file_path, "type": "text"}
        )

    return chunks


def parse_document(file_path: str) -> List[Dict[str, Any]]:
    """
    Parse a document based on its file extension.

    Args:
        file_path: Path to document file

    Returns:
        List of text chunks
    """
    path = Path(file_path)
    extension = path.suffix.lower()

    if extension == ".pdf":
        return parse_pdf(file_path)
    elif extension == ".csv":
        return parse_csv(file_path)
    elif extension in [".txt", ".md"]:
        return parse_text(file_path)
    else:
        raise ValueError(f"Unsupported file type: {extension}")
