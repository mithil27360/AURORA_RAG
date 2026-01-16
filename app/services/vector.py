

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
        # Use 2 threads per embedding for better CPU utilization on multi-core systems
        self.model = TextEmbedding(model_name=model_name, threads=2)

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
        
        # Concurrency Cap: Limit active embedding jobs to 4 (N_CORES * 2)
        self.sem = asyncio.Semaphore(4)
        
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
            # Do not pass embedding_function to avoid conflict with persisted config
            # We handle embedding manually at query time via _get_query_embedding
            self.collection = self.db.get_collection(name=self.active_collection_name)
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
            processed = []
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
        
        # Generic terms that should NOT trigger event-specific matching
        EXCLUDED_WORDS = {
            'aurora', 'fest', 'iste', 'manipal', 'event', 'events', 'workshop', 'workshops',
            'hackathon', 'hackathons', 'speaker', 'speakers', 'sponsor', 'sponsors', 
            'team', 'contact', 'schedule', 'venue', 'registration', 'about', 'what', 'who',
            'when', 'where', 'how', 'list', 'all', 'tell', 'give', 'details', 'info'
        }
        
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

        # 3. Word-based Difflib (Skip generic/excluded words)
        for word in query.split():
            if len(word) < 4: continue
            if word.lower() in EXCLUDED_WORDS: continue  # Skip generic terms
            m = difflib.get_close_matches(word, event_names, n=1, cutoff=0.6)
            if m:
                found.add(m[0])
        
        return list(found)

    async def update_kb(self, events: List[Dict], force: bool = False):
        """Update Knowledge Base (Blue/Green) - non-blocking wrapper"""
        await asyncio.to_thread(self._sync_update, events, force)
        
    def _sync_update(self, events: List[Dict], force: bool = False):
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
            
            # Safety check: Prevent accidental massive deletion (unless forced)
            if not force and old_count > 0 and new_count < (old_count * 0.8):
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
                "text": """ABOUT AURORA CHATBOT: I am the Aurora Fest Assistant, an AI built to help you navigate the ISTE Aurora 2026 college fest at MIT Manipal. I can help with event schedules, registration, workshops, hackathons, and more. Aurora is organized by ISTE Manipal (Indian Society for Technical Education, Students' Chapter).""",
                "metadata": {"type": "about", "topic": "identity"}
            },
            {
                "id": "about_chief_guest",
                "text": """AURORA CHIEF GUEST: The Chief Guest for Aurora Fest 2026 inauguration ceremony is yet to be officially announced. Please check ISTE Manipal's social media handles and official website for updates. We usually invite prominent industry leaders or scientists.""",
                "metadata": {"type": "about", "topic": "guest"}
            },
            # ===== SPEAKER SESSION =====
            {
                "id": "speaker_aparna_debnath",
                "text": """SPEAKER SESSION: Career beyond the syllabus - Aparna Debnath. She is Assistant Vice President at Barclays, Lead Business Analyst, and was Featured at Times Square NY. This session helps students understand how careers in finance and technology actually evolve beyond college. Learn how engineers transition into global financial institutions, explore business-technology hybrid roles like Business Analyst and Product Manager, and understand why communication, confidence, and adaptability accelerate long-term career growth. Venue: Library Auditorium. Date: 19th January 2026. Time: 6pm onwards.""",
                "metadata": {"type": "speaker", "topic": "career", "date": "2026-01-19"}
            },
            # ===== AURORA CTF =====
            {
                "id": "aurora_ctf_details",
                "text": """AURORA CTF: AuroraCTF is a 30-hour Capture The Flag cybersecurity competition. This isn't just a CTF; it's a test of dominance. Challenges include Cryptography, Reverse Engineering, and Web Exploitation. Dates: 21st January 6:00 PM to 22nd January 11:59 PM (2026). Prize Pool: 1st Place ₹4,000, 2nd Place ₹2,500, 3rd Place ₹1,500. Objective: pwn everything.""",
                "metadata": {"type": "competition", "topic": "ctf", "date": "2026-01-21"}
            },
            # ===== DEVSPRINT HACKATHON =====
            {
                "id": "devsprint_hackathon",
                "text": """DEVSPRINT HACKATHON: Learn. Build. Compete. DevSprint is a 10-hour coding marathon (12 hours total event time from 7:00 AM to 7:00 PM on 25th January 2026). The day includes coding time, mini-games, and a final presentation session. Team size: 2-5 participants. Prize Pool: 1st Place ₹8,000, 2nd Place ₹5,000, 3rd Place ₹3,000. Certificates of participation for all participants. Teams must bring their own laptops; venue provides internet. Mini-games can slightly boost your score but preference is given to your app. Registration is on the AURORA website.""",
                "metadata": {"type": "hackathon", "topic": "devsprint", "date": "2026-01-25"}
            },
            # ===== SPONSORS =====
            {
                "id": "aurora_sponsors",
                "text": """Who are the sponsors of Aurora? What companies sponsor Aurora Fest? AURORA SPONSORS AND PARTNERS: Title Sponsor - Global Degrees (premier partner committed to excellence and innovation, supporting the next generation of tech leaders). Co-Powered By - Aniche Studios (represents unique style and quality, celebrating creativity and individuality). Associate Sponsors - Burger Shack (juicy burgers with secret sauce and fresh ingredients in Manipal), Cafe Story (cozy ambiance with premium coffee in Manipal), Noch (premium experiences and student support), SAB Consultancy Services (Student Advisory Board - apex student body of MIT bridging gap between administration and students). These sponsors power the future of technology at Aurora Fest 2026.""",
                "metadata": {"type": "about", "topic": "sponsors"}
            },
            # ===== CONTACT INFO =====
            {
                "id": "aurora_contact",
                "text": """How to contact ISTE? What is the contact information for Aurora Fest? AURORA CONTACT DETAILS: Email: aurora.istemanipal@gmail.com. Phone: +91-8809795723. Location: Manipal, Udupi, Karnataka, India. For event-specific queries, check the contact details on each event page or reach out to the respective club coordinators. Contact ISTE Manipal at aurora.istemanipal@gmail.com or call +91-8809795723.""",
                "metadata": {"type": "contact", "topic": "general"}
            },
            # ===== TEAM =====
            {
                "id": "aurora_team_board",
                "text": """AURORA BOARD MEMBERS (ISTE Manipal Leadership): Abhinav Kumar, Pranav Kumar, Navaneeth Suresh, Hrithiq Gupta, Mayank Kejariwal, Pranav Kasliwal, Vasavi A Saralaya, Sonaksh Jain. These are the minds behind the magic of Aurora Fest 2026.""",
                "metadata": {"type": "about", "topic": "team"}
            },
            {
                "id": "aurora_team_dev",
                "text": """AURORA DEV TEAM: Sumeet (Full-Stack Tester), Mohammad Arsh, Pravar Singh, Divij Manchanda, Tanseer Ahmad, Powel Lawrence Lewis, Arkadeep Das, Viraj Rahul Gupta, Prayatshu. They build and maintain the Aurora website and technical infrastructure.""",
                "metadata": {"type": "about", "topic": "team"}
            },
            {
                "id": "aurora_team_design",
                "text": """AURORA DESIGN TEAM: Samyak Jain, Aarav Sadhu, Rohit Nema. They create the visual identity and graphics for Aurora Fest.""",
                "metadata": {"type": "about", "topic": "team"}
            },
            {
                "id": "aurora_team_ml",
                "text": """AURORA ML TEAM: Mithil S (builds the Aurora RAG Chatbot), Bhuvi Sanga. They work on AI/ML projects and the Aurora chatbot.""",
                "metadata": {"type": "about", "topic": "team"}
            },
            # ===== AURORA TIMELINE =====
            {
                "id": "aurora_timeline",
                "text": """AURORA 2026 EVENT TIMELINE: 19th Jan - Speaker Session (Aparna Debnath, Career beyond the syllabus). 20th-24th Jan - Workshops (hands-on sessions led by experts). 21st-22nd Jan - AuroraCTF (30-hour CTF competition). 25th Jan - DevSprint Hackathon (12-hour coding marathon).""",
                "metadata": {"type": "schedule", "topic": "timeline"}
            },
            # ===== HELP / FAQ TOPICS (Added based on user feedback) =====
            {
                "id": "help_payment_pending",
                "text": """PAYMENT PENDING / TRANSACTION FAILED: If your payment status shows 'pending' or money was deducted but not reflected, please do not panic. It can take up to 24 hours for the payment gateway to synchronize status. Action: Wait for a little bit (up to 24 hours). If it still doesn't update, please contact the organizers or the technical team with your Transaction ID, or just visit the registration desk for immediate assistance.""",
                "metadata": {"type": "help", "topic": "payment"}
            },
            {
                "id": "help_edit_profile",
                "text": """EDIT PROFILE DETAILS: Currently, you cannot edit your profile details (Name, Email, Registration Number) directly in the app once registered. If you made a mistake, please contact the ISTE Registration Desk at the venue or email aurora.istemanipal@gmail.com with your correct details.""",
                "metadata": {"type": "help", "topic": "profile"}
            },
            {
                "id": "help_venues_general",
                "text": """WORKSHOP VENUES / LOCATIONS: The specific venue for each workshop is listed on its event detail page in the app or website. Generally, workshops are held in AB5 (Academic Block 5) or the Library. Please check the specific event card for the exact room number.""",
                "metadata": {"type": "help", "topic": "venue"}
            },
            {
                "id": "summary_ai_workshops",
                "text": """AI ARTIFICIAL INTELLIGENCE WORKSHOPS: There are several AI-focused workshops at Aurora Fest 2026: 1. 'AI-Driven Generative Design System Using StyleGAN3' by ACM Manipal (Jan 22nd). 2. 'OpenCV Workshop' by RUGVED (Jan 24th) covering AI-driven computer vision. 3. 'Sentiment to Signal' by Finova (Jan 22nd) involves AI-based trading decisions. Check these specific events for details.""",
                "metadata": {"type": "summary", "topic": "ai"}
            }
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
            sdate = str(ev.get('start_date', '')).replace('2055', '2026')
            edate = str(ev.get('end_date', '')).replace('2055', '2026')
            
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
            start_date = event.get('start_date')
            start_time = event.get('start_time')
            end_time = event.get('end_time')
            venue = event.get('venue')
            day_num = event.get('day_num', '1')
            event_name = event.get('event_name', 'Unknown Event')
            event_type = event.get('event_type', 'Event')
            
            # Use raw start_date as string without sanitization (preserves 2055)
            sdate_str = str(event.get('start_date', ''))
            
            # Calculate actual date based on Day number
            # Default to sdate, but try to offset if day > 1
            final_date_str = sdate_str
            try:
                day_str = str(day_num)
                if sdate_str and day_str.isdigit() and int(day_str) > 1:
                    from datetime import datetime, timedelta
                    start_dt = datetime.strptime(sdate_str, "%Y-%m-%d")
                    offset_dt = start_dt + timedelta(days=int(day_str) - 1)
                    final_date_str = offset_dt.strftime("%Y-%m-%d")
            except Exception as e:
                logger.warning(f"Date parsing failed for {event_name}: {e}")

            # Schedule
            if event.get("start_time"):
                text = f"SCHEDULE: {event_name} ({event_type}) Day {day_num} on {final_date_str} from {event.get('start_time', '')} to {event.get('end_time', '')}."
                if event.get("venue"):
                    text += f" Venue: {event.get('venue')}."
                chunks.append({
                    "id": f"{event_name}_schedule_day{day_num}",
                    "text": text,
                    "metadata": {"event": event_name, "type": "schedule"}
                })
            
            # Topics / Description
            topics = event.get("topics_covered") or event.get("project_description") or event.get("event_description")
            if topics:
                chunks.append({
                    "id": f"{event_name}_topics_day{day_num}",
                    "text": f"**EVENT DETAILS** for {event_name}: {topics}",
                    "metadata": {"event": event_name, "type": "description"}
                })
            
            # Prerequisites
            prereqs = event.get("prerequisites")
            if prereqs:
                chunks.append({
                    "id": f"{event_name}_prereqs_day{day_num}",
                    "text": f"PREREQUISITES for {event_name}: {prereqs}",
                    "metadata": {"event": event_name, "type": "rules"}
                })
            
            # Contact (deduplicated)
            contact = event.get("contact_name") or event.get("contact_mail")
            if contact and event_name not in added_contacts:
                text = f"CONTACT for {event_name}: {event.get('contact_name', '')}. Email: {event.get('contact_mail', '')}. Phone: {event.get('contact_phone', '')}."
                chunks.append({
                    "id": f"{event_name}_contact",
                    "text": text,
                    "metadata": {"event": event_name, "type": "contact"}
                })
                added_contacts.add(event_name)
        
        logger.info(f"Generated {len(chunks)} chunks from {len(events)} rows ({len(unique_events)} unique events)")
        return chunks

vector_service = VectorService()

def get_vector_service():
    return vector_service
