"""Locust load testing for Aurora RAG Chatbot."""
from locust import HttpUser, task, between

class AuroraUser(HttpUser):
    wait_time = between(1, 3)

    @task(1)
    def health_check(self):
        self.client.get("/health")

    @task(5)
    def chat(self):
        self.client.post("/chat", json={"query": "What events are happening?"})

    @task(2)
    def chat_schedule(self):
        self.client.post("/chat", json={"query": "When is the hackathon?"})
