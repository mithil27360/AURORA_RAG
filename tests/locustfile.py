from locust import HttpUser, task, between
import random

class AuroraUser(HttpUser):
    wait_time = between(1, 3)  # Simulate real user think time (1-3s)

    @task(10)
    def health_check(self):
        """Lightweight check - high volume"""
        self.client.get("/health")

    @task(5)
    def view_dashboard(self):
        """Moderate check - viewing analytics"""
        self.client.get("/dashboard", auth=("admin", "aurora2025"))

    @task(3)
    def chat_general(self):
        """Heavy check - General Chat (RAG pipeline)"""
        queries = [
            "Hi",
            "What is Aurora Fest?",
            "Tell me about ISTE",
            "Who are the organizers?",
            "Is there a hackathon?"
        ]
        self.client.post("/chat", json={"query": random.choice(queries)})

    @task(1)
    def chat_specific(self):
        """Heavy check - Specific Event Chat (Vector Search)"""
        queries = [
            "When is the PCB workshop?",
            "What are the rules for the Hackathon?",
            "Where is the UI/UX workshop?",
            "Details about Astravaganza"
        ]
        self.client.post("/chat", json={"query": random.choice(queries)})

    def on_start(self):
        """Called when a virtual user starts"""
        pass
