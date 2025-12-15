import chromadb
import uuid

class MemoryAgent:
    def __init__(self, db_path="./memory_db"):
        self.client = chromadb.PersistentClient(path=db_path)
        
        # Collection for "Rules" (Feedback & Rejections)
        self.rules_collection = self.client.get_or_create_collection(name="testing_rules")
        
        # Collection for "Examples" (Accepted Tests)
        self.examples_collection = self.client.get_or_create_collection(name="accepted_tests")

    def remember_rejection(self, test_name, feedback, page_context):
        """Stores a lesson from a rejected test."""
        self.rules_collection.add(
            documents=[f"REJECTED: {test_name}. REASON: {feedback}"],
            metadatas=[{"type": "negative_constraint", "context": page_context}],
            ids=[str(uuid.uuid4())]
        )

    def remember_acceptance(self, test_name, description, page_context):
        """Stores a good test case as a template."""
        self.examples_collection.add(
            documents=[f"ACCEPTED: {test_name} - {description}"],
            metadatas=[{"type": "positive_example", "context": page_context}],
            ids=[str(uuid.uuid4())]
        )

    def retrieve_context(self, current_page_context):
        """Finds relevant past lessons for the current page."""
        # Retrieve top 3 relevant negative rules
        negatives = self.rules_collection.query(
            query_texts=[current_page_context],
            n_results=3
        )
        
        # Retrieve top 3 relevant positive examples
        positives = self.examples_collection.query(
            query_texts=[current_page_context],
            n_results=3
        )

        return {
            "avoid": [doc for doc in negatives['documents'][0]],
            "emulate": [doc for doc in positives['documents'][0]]
        }