

import logging
import time
import asyncio
import chromadb
import difflib
import re
from typing import List, Dict, Optional
from functools import lru_cache
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings
from fastembed import TextEmbedding
from app.core.config import settings

logger = logging.getLogger(__name__)

# --- FastEmbed Wrapper for ChromaDB ---
class FastEmbedEmbeddingFunction(EmbeddingFunction):
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self.model = TextEmbedding(model_name=model_name, threads=1) # 1 thread per model (we handle concurrency via app)

    def __call__(self, input: Documents) -> Embeddings:
        # FastEmbed returns a generator, convert to list
        return list(self.model.embed(input))

# --------------------------------------

class VectorService:
    def __init__(self):
        # Initialize FastEmbed (ONNX + Quantized)
        try:
            self.embedding = FastEmbedEmbeddingFunction()
            logger.info("Initialized FastEmbed")
        except Exception as e:
            logger.error(f"FastEmbed failed, falling back to SentenceTransformers: {e}")
            from chromadb.utils import embedding_functions
            self.embedding = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name="all-MiniLM-L6-v2"
            )

        self.db = chromadb.PersistentClient(path=str(settings.CHROMA_PATH))
        self.active_collection_name = None
        self.collection = None
        
        # Concurrency Cap: Limit active embedding jobs to 3
        self.sem = asyncio.Semaphore(3)
        
        # Initialize (Blocking ok on startup)
        self._init_collection()

    def _init_collection(self):
        """Find latest collection or create new"""
        collections = self.db.list_collections()
        aurora_cols = [c.name for c in collections if c.name.startswith("Aurora_v_")]
        
        if aurora_cols:
            # Sort by timestamp (Aurora_v_TIMESTAMP)
            aurora_cols.sort(key=lambda x: int(x.split("_")[-1]), reverse=True)
            self.active_collection_name = aurora_cols[0]
            self.collection = self.db.get_collection(
                name=self.active_collection_name, 
                embedding_function=self.embedding
            )
            logger.info(f"Loaded existing collection: {self.active_collection_name} ({self.collection.count()} docs)")
        else:
            # First run
            self.active_collection_name = f"Aurora_v_{int(time.time())}"
            self.collection = self.db.create_collection(
                name=self.active_collection_name, 
                embedding_function=self.embedding,
                metadata={"hnsw:space": "cosine"}
            )
            logger.info(f"Created new collection: {self.active_collection_name}")

    # Aggressive Caching for Query Embeddings
    @lru_cache(maxsize=1000)
    def _get_query_embedding(self, query: str):
        """
        Cache embedding for frequent queries.
        Input must be normalized before hitting this cache to ensure hit rate.
        """
        return self.embedding([query])[0]
            
    async def search(self, query: str, k: int = None, filters: Dict = None):
        """Async wrapper for search with timeout handling and concurrency cap."""
        if not self.collection:
            return []

        # Parse and normalize input
        # This ensures consistent cache hits for case-insensitive matches.
        query = query.strip().lower() if query else ""
            
        # asyncio.Semaphore ensures FIFO behavior for fairness.
        async with self.sem:
            def _sync_search():
                # We simply pass the query text and Chroma handles the embedding using our function
                # OPTIMIZATION: If we wanted to use our Cached Embedding, we would manually embed here.
                # Since Chroma's .query() takes string OR embedding, let's use our cache!
                
                query_vec = self._get_query_embedding(query)
                
                if filters:
                     return self.collection.query(
                        query_embeddings=[query_vec], 
                        n_results=k,
                        where=filters
                    )
                else:
                    return self.collection.query(query_embeddings=[query_vec], n_results=k)

            try:
                # Run in thread pool with timeout
                results = await asyncio.wait_for(
                    asyncio.to_thread(_sync_search),
                    timeout=settings.vector.timeout_seconds if hasattr(settings, 'vector') else 10.0
                )
            except asyncio.TimeoutError:
                logger.error("ChromaDB search timed out", extra={"query": query[:50]})
                return []  # Return empty, let LLM handle "no context found"
            except Exception as e:
                if "does not exist" in str(e):
                    logger.warning(f"Collection missing during search, refreshing: {e}")
                    self._init_collection()
                    # Retry once
                    try:
                         results = await asyncio.wait_for(
                            asyncio.to_thread(_sync_search),
                            timeout=settings.vector.timeout_seconds if hasattr(settings, 'vector') else 10.0
                        )
                    except Exception as retry_err:
                        logger.error(f"Search retry failed: {retry_err}")
                        return []
                else:
                    logger.error(f"ChromaDB search error: {e}")
                    return []  # Graceful degradation
            
            # Process results
            if results["documents"]:
                for i, doc in enumerate(results["documents"][0]):
                    dist = results["distances"][0][i]
                    meta = results["metadatas"][0][i]
                    doc_id = results["ids"][0][i]
                    
                    # Similarity conversion
                    similarity = max(0.0, 1.0 - (dist / 2.0))
                    
                    if similarity >= settings.vector.confidence_threshold:
                        processed.append({
                            "text": doc,
                            "score": similarity,
                            "distance": dist,
                            "id": doc_id,
                            "meta": meta
                        })
                    
        return sorted(processed, key=lambda x: x["score"], reverse=True)

    async def get_master_event_list(self) -> Dict:
        """Retrieve the master event list chunk directly."""
        if not self.collection:
            self._init_collection()
            if not self.collection:
                return None
            
        try:
            result = await asyncio.to_thread(
                self.collection.get,
                ids=["master_event_list"]
            )
            if result and result["documents"]:
                return {
                    "text": result["documents"][0],
                    "score": 1.0, 
                    "id": "master_event_list",
                    "meta": result["metadatas"][0] if result["metadatas"] else {}
                }
        except Exception as e:
            if "does not exist" in str(e):
                logger.warning(f"Collection missing during master fetch, refreshing: {e}")
                self._init_collection()
                # Retry once
                try:
                    result = await asyncio.to_thread(self.collection.get, ids=["master_event_list"])
                    if result and result["documents"]:
                        return {
                            "text": result["documents"][0],
                            "score": 1.0,
                            "id": "master_event_list",
                            "meta": result["metadatas"][0] if result["metadatas"] else {}
                        }
                except Exception as retry_err:
                    logger.error(f"Master fetch retry failed: {retry_err}")
            else:
                logger.error(f"Failed to fetch master list: {e}")
        return None

    async def fuzzy_search_event(self, query: str) -> List[str]:
        """Find event names that match the query fuzzily."""
        master = await self.get_master_event_list()
        if not master:
            return []
        
        # Extract names from text: "1. EventName (Type) - "
        text = master.get("text", "")
        # Regex to find "1. Name (Type)" -> Capture Name
        pattern = r"\d+\.\s+(.*?)\s+\("
        event_names = re.findall(pattern, text)
        
        # 1. Normalize query for substring check
        query_alnum = re.sub(r'[^a-z0-9]', '', query.lower())
        
        found = set()
        
        for name in event_names:
            # Normalize name: "Intro to UI/UX" -> "introtouiux"
            name_alnum = re.sub(r'[^a-z0-9]', '', name.lower())
            if len(query_alnum) > 3 and query_alnum in name_alnum:
                found.add(name)

        # 2. Existing Difflib (Whole Query)
        matches = difflib.get_close_matches(query, event_names, n=1, cutoff=0.6)
        if matches:
            found.add(matches[0])

        # 3. Word-based Difflib
        for word in query.split():
            if len(word) < 4: continue
            m = difflib.get_close_matches(word, event_names, n=1, cutoff=0.6)
            if m:
                found.add(m[0])
        
        return list(found)

    async def update_kb(self, events: List[Dict]):
        """Update Knowledge Base (Blue/Green) - non-blocking wrapper"""
        await asyncio.to_thread(self._sync_update, events)
        
    def _sync_update(self, events: List[Dict]):
        """Synchronous update logic"""
        try:
            chunks = self._chunk_events(events)
            if not chunks:
                logger.warning("No chunks generated from events")
                return

            new_version = f"Aurora_v_{int(time.time())}"
            logger.info(f"Creating new collection: {new_version}")
            
            new_col = self.db.create_collection(
                name=new_version,
                embedding_function=self.embedding,
                metadata={"hnsw:space": "cosine"}
            )
            
            # Batch load
            batch_size = 100
            for i in range(0, len(chunks), batch_size):
                batch = chunks[i:i+batch_size]
                new_col.add(
                    ids=[c["id"] for c in batch],
                    documents=[c["text"] for c in batch],
                    metadatas=[c["metadata"] for c in batch]
                )
            
            # Verification
            new_count = new_col.count()
            old_count = self.collection.count() if self.collection else 0
            
            if old_count > 0 and new_count < (old_count * 0.8):
                logger.error(f"Update Unsafe: {new_count} < 80% of {old_count}. Aborting.")
                self.db.delete_collection(new_version)
                return
                
            # Swap
            self.collection = new_col
            self.active_collection_name = new_version
            logger.info(f"Swapped to {new_version}")
            
            # Cleanup
            self._cleanup_old()
            
        except Exception as e:
            if "does not exist" in str(e):
                logger.debug(f"Collection sync race condition (expected): {e}")
            else:
                logger.error(f"Update failed: {e}")

    def _cleanup_old(self):
        """Keep last 3 versions"""
        cols = self.db.list_collections()
        aurora_cols = [c.name for c in cols if c.name.startswith("Aurora_v_")]
        aurora_cols.sort(key=lambda x: int(x.split("_")[-1]), reverse=True)
        
        for old_name in aurora_cols[3:]:
            try:
                self.db.delete_collection(old_name)
                logger.info(f"Deleted old collection: {old_name}")
            except Exception as e:
                if "does not exist" in str(e):
                    logger.debug(f"Collection already deleted: {old_name}")
                else:
                    logger.error(f"Unexpected deletion error: {e}")

    def _chunk_events(self, events: List[Dict]) -> List[Dict]:
        """Convert events to RAG chunks with master list for 'all events' queries.
        
        Creates:
        - Master event list (critical for "what are all events" query)
        - Events by type (workshops, hackathons, etc.)
        - Per-event overview (deduplicated)
        - Per-day schedule, topics, prerequisites, contact chunks
        - FAQs (question-answer pairs)
        """
        chunks = []
        
        # ===== STATIC "ABOUT" CHUNKS (General info not in Sheets) =====
        static_chunks = [
            {
                "id": "about_iste_manipal",
                "text": """ABOUT ISTE MANIPAL: ISTE Manipal stands for the Indian Society for Technical Education, Students' Chapter - a large, multi-disciplinary technical club at the Manipal Institute of Technology (MIT), Manipal Academy of Higher Education (MAHE). ISTE Manipal is a student community focused on advancing student skills through technical and non-technical initiatives including workshops, hackathons, and guest speaker events. Key activities include ACUMEN (technical event series), AURORA (annual tech week), Summer/Winter School (foundational learning in DSA, AI/ML), and Tech Tatva. The club operates across Technical domains (App/Web Development, Coding, AI/ML) and Non-Technical domains (Graphics Design, Content Writing, HR, PR). It is one of MIT Manipal's largest student clubs with active memberships nationally, led by a student board and management committee.""",
                "metadata": {"type": "about", "topic": "iste"}
            },
            {
                "id": "about_aurora_fest",
                "text": """ABOUT AURORA: Aurora is the annual flagship technical week (tech fest) organized by ISTE Manipal at MIT Manipal. Described as the 'biggest tech week of Manipal', it is a multi-day extravaganza designed to foster innovation, creativity, and technical learning. Key features include: Workshops (hands-on sessions on OpenCV, AI/ML, web development, cryptography), Competitions (hackathons like Hackspark, CTF events, coding contests, treasure hunts), Guest Speakers (industry leaders and entrepreneurs sharing insights), and Collaborations with other clubs (ACM Manipal, Astronomy Club, Project Dronaid). Aurora provides a platform for students to turn ideas into reality, form connections with mentors and alumni, and begin their journey toward technical mastery.""",
                "metadata": {"type": "about", "topic": "aurora"}
            },
            {
                "id": "about_registration",
                "text": """AURORA REGISTRATION: To register for Aurora Fest events, visit the official AURORA website. Registration is required for most workshops and hackathons. Each event may have different registration deadlines, so check the specific event details. Certificates are provided for most workshops upon completion.""",
                "metadata": {"type": "about", "topic": "registration"}
            },
            {
                "id": "about_identity_repo",
                "text": """ABOUT AURORA CHATBOT: I am the Aurora Fest Assistant, an AI built to help you navigate the ISTE Aurora 2025 college fest at MIT Manipal. I can help with event schedules, registration, workshops, hackathons, and more. Aurora is organized by ISTE Manipal (Indian Society for Technical Education, Students' Chapter).""",
                "metadata": {"type": "about", "topic": "identity"}
            },
            {
                "id": "about_chief_guest",
                "text": """AURORA CHIEF GUEST: The Chief Guest for Aurora Fest 2025 inauguration ceremony is yet to be officially announced. Please check ISTE Manipal's social media handles and official website for updates. We usually invite prominent industry leaders or scientists.""",
                "metadata": {"type": "about", "topic": "guest"}
            },
        ]
        chunks.extend(static_chunks)
        
        # ===== Separate FAQs from Events =====
        faqs = [e for e in events if e.get("_is_faq")]
        events = [e for e in events if not e.get("_is_faq")]
        
        # ===== FAQ CHUNKS =====
        for i, faq in enumerate(faqs):
            q = faq.get("question", "")
            a = faq.get("answer", "")
            event_name = faq.get("event_name", "General")
            category = faq.get("category", "")
            
            text = f"FAQ: {q}\nAnswer: {a}"
            if event_name and event_name != "General":
                text = f"FAQ about {event_name}: {q}\nAnswer: {a}"
            
            chunks.append({
                "id": f"faq_{i}",
                "text": text,
                "metadata": {"type": "faq", "event": event_name, "category": category}
            })
        
        if faqs:
            logger.info(f"Created {len(faqs)} FAQ chunks")
        
        # ===== PASS 1: Collect unique events & Min Dates =====
        event_groups = {} # {name: [rows]}
        
        for event in events:
            name = event.get("event_name", "Unknown").strip()
            if name not in event_groups:
                event_groups[name] = []
            event_groups[name].append(event)

        # Sort events by min start_date
        def get_min_date(name):
             rows = event_groups[name]
             dates = [r.get("start_date", "9999-99-99") for r in rows if r.get("start_date")]
             return min(dates) if dates else "9999-99-99"

        sorted_names = sorted(event_groups.keys(), key=get_min_date)

        # ===== MASTER EVENT LIST (Critical for "all events" queries) =====
        master_list = "**ALL EVENT SUMMARIES** (Read these for relevance):\n"
        for i, name in enumerate(sorted_names, 1):
            rows = event_groups[name]
            # Use first row for static details, but calculate date range
            ev = rows[0]
            start_date = get_min_date(name)
            
            # Find max date
            all_dates = [r.get("start_date") for r in rows if r.get("start_date")]
            end_date = max(all_dates) if all_dates else start_date
            
            date_str = f"({start_date})"
            if start_date != end_date:
                date_str = f"({start_date} to {end_date})"

            # Add truncated description to master list for better context
            description = ev.get('event_description') or ev.get('project_description') or ""
            short_desc = " ".join(description.split()[:15]) + "..." if description else ""
            
            master_list += f"{i}. {name} ({ev.get('event_type', 'Event')}) - by {ev.get('club_name', 'Aurora Team')} {date_str} - {short_desc}\n"

        chunks.append({
            "id": "master_event_list",
            "text": master_list,
            "metadata": {"type": "event_list", "count": len(sorted_names)}
        })

        # Re-populate helper dicts for downstream logic (keeping existing logic happy)
        unique_events = {name: event_groups[name][0] for name in sorted_names}
        events_by_type = {}
        events_by_club = {}
        for name in sorted_names:
            ev = unique_events[name]
            etype = ev.get("event_type", "Event")
            if etype not in events_by_type: events_by_type[etype] = []
            events_by_type[etype].append(name)
            
            club = ev.get("club_name", "")
            if club:
                if club not in events_by_club: events_by_club[club] = []
                events_by_club[club].append(name)
        
        # ===== EVENTS BY TYPE =====
        for etype, names in events_by_type.items():
            text = f"{etype.upper()}S AT AURORA FEST:\n" + "\n".join([f"- {n}" for n in names])
            chunks.append({
                "id": f"events_type_{etype.lower().replace(' ', '_')}",
                "text": text,
                "metadata": {"type": "event_list", "event_type": etype}
            })
        
        # ===== EVENTS BY CLUB =====
        for club, names in events_by_club.items():
            club_id = club.lower().replace(' ', '_').replace(',', '').replace('-', '_')
            text = f"EVENTS BY {club}: " + ", ".join(names)
            chunks.append({
                "id": f"events_club_{club_id}",
                "text": text,
                "metadata": {"type": "event_list", "club": club}
            })
        
        # ===== PER-EVENT OVERVIEW (Deduplicated) =====
        for name, ev in unique_events.items():
            club = ev.get('club_name', '')
            
            # Sanitize dates (Fix common 2055 typo)
            sdate = str(ev.get('start_date', '')).replace('2055', '2025')
            edate = str(ev.get('end_date', '')).replace('2055', '2025')
            
            overview = f"""EVENT: {name}
Type: {ev.get('event_type', 'Event')}
Organized by: {club}
Dates: {sdate} to {edate}
Description: {ev.get('event_description') or ev.get('project_description') or ev.get('topics_covered', 'No description available.')}
Registration: {ev.get('registration_required', 'No')}
Certificate: {ev.get('certificate_offered', 'No')}"""
            
            chunks.append({
                "id": f"{name}_overview",
                "text": overview,
                "metadata": {"event": name, "type": "general"}
            })
            
            # Dedicated club/organizer chunk for "which club" queries
            if club:
                chunks.append({
                    "id": f"{name}_club",
                    "text": f"CLUB/ORGANIZER: {name} is organized/conducted by {club}. The club responsible for {name} is {club}.",
                    "metadata": {"event": name, "type": "general", "club": club}
                })
        
        # ===== PER-DAY CHUNKS =====
        added_contacts = set()  # Track to avoid duplicates
        
        for event in events:
            name = event.get("event_name", "Unknown").strip()
            day = event.get("day_num", "1")
            etype = event.get("event_type", "Event")
            
            # Sanitize dates (Fix common 2055 typo)
            sdate_str = str(event.get('start_date', '')).replace('2055', '2025')
            
            # Calculate actual date based on Day number
            # Default to sdate, but try to offset if day > 1
            final_date_str = sdate_str
            try:
                if sdate_str and day.isdigit() and int(day) > 1:
                    from datetime import datetime, timedelta
                    start_dt = datetime.strptime(sdate_str, "%Y-%m-%d")
                    offset_dt = start_dt + timedelta(days=int(day) - 1)
                    final_date_str = offset_dt.strftime("%Y-%m-%d")
            except Exception as e:
                logger.warning(f"Date parsing failed for {name}: {e}")

            # Schedule
            if event.get("start_time"):
                text = f"SCHEDULE: {name} ({etype}) Day {day} on {final_date_str} from {event.get('start_time', '')} to {event.get('end_time', '')}."
                if event.get("venue"):
                    text += f" Venue: {event.get('venue')}."
                chunks.append({
                    "id": f"{name}_schedule_day{day}",
                    "text": text,
                    "metadata": {"event": name, "type": "schedule"}
                })
            
            # Topics / Description
            topics = event.get("topics_covered") or event.get("project_description") or event.get("event_description")
            if topics:
                chunks.append({
                    "id": f"{name}_topics_day{day}",
                    "text": f"**EVENT DETAILS** for {name}: {topics}",
                    "metadata": {"event": name, "type": "description"}
                })
            
            # Prerequisites
            prereqs = event.get("prerequisites")
            if prereqs:
                chunks.append({
                    "id": f"{name}_prereqs_day{day}",
                    "text": f"PREREQUISITES for {name}: {prereqs}",
                    "metadata": {"event": name, "type": "rules"}
                })
            
            # Contact (deduplicated)
            contact = event.get("contact_name") or event.get("contact_mail")
            if contact and name not in added_contacts:
                text = f"CONTACT for {name}: {event.get('contact_name', '')}. Email: {event.get('contact_mail', '')}. Phone: {event.get('contact_phone', '')}."
                chunks.append({
                    "id": f"{name}_contact",
                    "text": text,
                    "metadata": {"event": name, "type": "contact"}
                })
                added_contacts.add(name)
        
        logger.info(f"Generated {len(chunks)} chunks from {len(events)} rows ({len(unique_events)} unique events)")
        return chunks

vector_service = VectorService()

def get_vector_service():
    return vector_service
