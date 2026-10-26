"""Seed Neo4j with quiz knowledge and demonstrate semantic retrieval.

Required environment variables: NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD,
and GEMINI_API_KEY. Keep them in an ignored local .env file or a secret store.
"""

import argparse
import json
import os
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from neo4j import GraphDatabase

from rag_knowledge import knowledge_documents


EMBEDDING_MODEL = "gemini-embedding-2"
INDEX_NAME = "rag_knowledge"
TOP_K = 4


def required_env(name):
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Set {name} in your environment or ignored .env file.")
    return value


def embed_text(text, api_key, *, is_query):
    if is_query:
        formatted_text = f"task: search result | query: {text}"
    else:
        formatted_text = text

    payload = {
        "model": f"models/{EMBEDDING_MODEL}",
        "content": {"parts": [{"text": formatted_text}]},
    }
    request = Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{EMBEDDING_MODEL}:embedContent",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": api_key,
        },
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        result = json.load(response)
    return result["embedding"]["values"]


def document_embedding_text(document):
    return f"title: {document['title']} | text: {document['text']}"


def resolve_database(driver):
    configured_name = os.getenv("NEO4J_DATABASE")
    if configured_name:
        return configured_name

    with driver.session(database="system") as session:
        databases = {
            record["name"]
            for record in session.run(
                "SHOW DATABASES YIELD name, currentStatus "
                "WHERE currentStatus = 'online' AND name <> 'system' "
                "RETURN name"
            )
        }

    if "neo4j" in databases:
        return "neo4j"
    if len(databases) == 1:
        return next(iter(databases))
    if not databases:
        raise RuntimeError(
            "No online Neo4j database was found. Check the Aura instance is running."
        )
    raise RuntimeError(
        "More than one online Neo4j database was found. Set NEO4J_DATABASE "
        "to the database name in your local .env file."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "question",
        nargs="?",
        default="Which crews have the fastest completed repairs?",
        help="Natural-language query used to demonstrate vector retrieval.",
    )
    args = parser.parse_args()

    load_dotenv()
    api_key = required_env("GEMINI_API_KEY")
    uri = required_env("NEO4J_URI")
    username = required_env("NEO4J_USERNAME")
    password = required_env("NEO4J_PASSWORD")

    documents = knowledge_documents()
    embeddings = [
        embed_text(document_embedding_text(document), api_key, is_query=False)
        for document in documents
    ]
    dimensions = len(embeddings[0])
    if any(len(embedding) != dimensions for embedding in embeddings):
        raise RuntimeError("Gemini returned inconsistent embedding dimensions.")

    with GraphDatabase.driver(uri, auth=(username, password)) as driver:
        driver.verify_connectivity()
        database = resolve_database(driver)
        print(f"Connected to Neo4j database: {database}")
        with driver.session(database=database) as session:
            session.run(
                "CREATE CONSTRAINT rag_knowledge_id IF NOT EXISTS "
                "FOR (doc:Knowledge) REQUIRE doc.id IS UNIQUE"
            ).consume()
            session.run(
                f"CREATE VECTOR INDEX {INDEX_NAME} IF NOT EXISTS "
                "FOR (doc:Knowledge) ON (doc.embedding) "
                "OPTIONS {indexConfig: {"
                f"`vector.dimensions`: {dimensions}, "
                "`vector.similarity_function`: 'cosine'}}"
            ).consume()
            session.run(
                """
                UNWIND $documents AS item
                MERGE (doc:Knowledge {id: item.id})
                SET doc.title = item.title,
                    doc.kind = item.kind,
                    doc.tables = item.tables,
                    doc.text = item.text,
                    doc.embedding = item.embedding
                """,
                documents=[
                    {**document, "embedding": embedding}
                    for document, embedding in zip(documents, embeddings)
                ],
            ).consume()
            session.run("CALL db.awaitIndex($name, 300)", name=INDEX_NAME).consume()

            query_embedding = embed_text(args.question, api_key, is_query=True)
            if len(query_embedding) != dimensions:
                raise RuntimeError(
                    "The query embedding dimension differs from the indexed documents."
                )
            results = session.run(
                f"""
                CALL db.index.vector.queryNodes($index, $top_k, $embedding)
                YIELD node, score
                RETURN node.title AS title, node.kind AS kind,
                       node.text AS text, score
                ORDER BY score DESC
                """,
                index=INDEX_NAME,
                top_k=TOP_K,
                embedding=query_embedding,
            )
            retrieved = list(results)

    print(f"Retrieved {len(retrieved)} knowledge items for: {args.question}\n")
    for item in retrieved:
        print(f"[{item['kind']}] {item['title']} (score: {item['score']:.3f})")
        print(item["text"])
        print()


if __name__ == "__main__":
    main()
