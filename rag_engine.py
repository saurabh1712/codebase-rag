import os
import shutil
from dotenv import load_dotenv
from operator import itemgetter

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_google_genai import ChatGoogleGenerativeAI

from langchain_community.document_loaders.generic import GenericLoader
from langchain_community.document_loaders.parsers import LanguageParser
from langchain_text_splitters import RecursiveCharacterTextSplitter, Language

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.documents import Document
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser

from utils import clone_or_update_repo

load_dotenv()


# HELPER FUNCTIONS
def clean_directory(path: str):
    """Recursively deletes and recreates a directory to ensure a clean state."""
    if os.path.exists(path):
        shutil.rmtree(path)
    # Recreate the directory so it exists for future use
    os.makedirs(path, exist_ok=True)


def format_docs(docs: list[Document]) -> str:
    """Takes a list of document chunks and mashes them into one big context string for the LLM."""
    return "\n\n".join(doc.page_content for doc in docs)


class RAGSystem:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.repo_path = f"./temp_repos/{session_id}"
        self.db_path = f"./chroma_db/{session_id}"

        self.qa_chain = None
        self.retriever = None

        # LLM (Gemini 2.5 Flash)
        # Here using the fast model bcz code analysis needs speed.
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            temperature=0.1
        )

        # Embeddings (Fast, local model)
        self.embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )

        # Prompt: Forcing it to be a strict Code Archaeologist
        system_prompt = (
            "You are an expert Codebase Archaeologist. Analyze ONLY the retrieved documents "
            "to answer the question. Ground your answer strictly in the code context provided. "
            "If the answer is not present in the retrieved context, reply: "
            "'The answer is not present in the codebase.'\n\n"
            "Context:\n{context}"
        )
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{input}")
        ])

    def _load_all_documents(self) -> list[Document]:
        """
        Loads ONLY Python files.
        Note: This is the stable fix for the notorious 'lazy_parse' issue.
        """

        # Filtering files using glob="**/*.py"
        loader = GenericLoader.from_filesystem(
            self.repo_path,
            glob="**/*.py", # Pass the single parser object directly, not a dictionary map.
            parser=LanguageParser(language=Language.PYTHON, parser_threshold=500),
        )
        documents = loader.load()

        if not documents:
            print("Warning: No Python documents found in the repository.")

        return documents

    def load_and_index(self, repo_url: str):
        """Clone repo -> Load -> Split -> Embedd -> Build retrieval chain."""

        if not clone_or_update_repo(repo_url, self.repo_path):
            raise Exception(f"Failed to clone: {repo_url}")

        documents = self._load_all_documents()

        if len(documents) == 0:
            raise Exception("No documents found. Check repository contents or file filter.")

        # Split documents
        splitter = RecursiveCharacterTextSplitter.from_language(
            language=Language.PYTHON,
            chunk_size=2000,
            chunk_overlap=200
        )
        texts = splitter.split_documents(documents)

        # Build Chroma vector DB
        vector_db = Chroma.from_documents(
            documents=texts,
            embedding=self.embeddings,
            persist_directory=self.db_path
        )
        self.retriever = vector_db.as_retriever(search_kwargs={"k": 3})

        # Build LCEL retrieval chain
        document_chain = self.prompt | self.llm | StrOutputParser()

        # CRITICAL LCEL FIX: Use itemgetter to pull the string query out
        # of the input dictionary for the retriever. This fixes the 'dict has no attribute replace' error.
        self.qa_chain = (
                {
                    # 1 Grab the string query via itemgetter("input")
                    # 2 Feed it to the retriever
                    # 3 Format the docs
                    "context": itemgetter("input") | self.retriever | format_docs,
                    # Pass the original query string through to the prompt's input slot
                    "input": itemgetter("input")
                }
                | document_chain
        )

        print("RAG system initialized successfully.")

    def ask(self, query: str) -> dict:
        """Query the RAG system and retrieve source documents."""
        if not self.qa_chain:
            return {"result": "Error: DB not indexed.", "source_documents": []}

        # LCEL chains require the input to be a dict, so we wrapping the query.
        input_dict = {"input": query}

        # Call the LLM chain
        answer_text = self.qa_chain.invoke(input_dict)

        # Retrieve the source documents (The standalone retriever needs the raw STRING query)
        source_documents = self.retriever.invoke(query)

        # Return the result
        return {
            "result": answer_text,
            "source_documents": source_documents
        }