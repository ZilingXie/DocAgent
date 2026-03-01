import hashlib
from dataclasses import dataclass

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter


@dataclass
class ChunkConfig:
    chunk_size: int
    chunk_overlap: int


def split_documents(documents: list[Document], config: ChunkConfig) -> list[Document]:
    """Split documents by markdown headers then by chunk size."""
    header_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")],
        strip_headers=False,
    )
    length_splitter = RecursiveCharacterTextSplitter(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
    )

    all_chunks: list[Document] = []
    for doc in documents:
        header_docs = header_splitter.split_text(doc.page_content)
        if not header_docs:
            header_docs = [Document(page_content=doc.page_content, metadata={})]

        normalized_header_docs: list[Document] = []
        for header_doc in header_docs:
            merged_meta = {**doc.metadata, **header_doc.metadata}
            normalized_header_docs.append(
                Document(page_content=header_doc.page_content, metadata=merged_meta)
            )

        chunks = length_splitter.split_documents(normalized_header_docs)
        for idx, chunk in enumerate(chunks):
            chunk.metadata["chunk_index"] = idx
            chunk.metadata["chunk_id"] = f"{chunk.metadata['doc_id']}-{idx}"
            chunk.metadata["content_hash"] = hashlib.sha1(
                chunk.page_content.encode("utf-8")
            ).hexdigest()[:16]
            chunk.metadata["h1"] = str(chunk.metadata.get("h1", ""))
            chunk.metadata["h2"] = str(chunk.metadata.get("h2", ""))
            chunk.metadata["h3"] = str(chunk.metadata.get("h3", ""))
            all_chunks.append(chunk)
    return all_chunks
