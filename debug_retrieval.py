import asyncio
from app.services.vector import VectorService
from app.core.config import settings

async def main():
    vs = VectorService()
    query = "conveniant"
    print(f"Searching for: {query}")
    results = await vs.search(query, k=5)
    print(f"Found {len(results)} results")
    for r in results:
        print(f"[{r['score']:.4f}] {r['meta'].get('type')} - {r['meta'].get('event')}")
        print(f"Text snippet: {r['text'][:50]}...")
        print("-" * 20)

if __name__ == "__main__":
    asyncio.run(main())
