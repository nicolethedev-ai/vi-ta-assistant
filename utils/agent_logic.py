import asyncio
import os
from pathlib import Path
from agents import Agent, Runner, trace, function_tool, ModelSettings
from agents.mcp import MCPServerStdio
from pydantic import BaseModel, ConfigDict, Field
from typing import List, Optional, Dict
from tavily import TavilyClient
from dotenv import load_dotenv
import json
from datetime import datetime, timedelta

load_dotenv(override=True)

from .database import (
    create_memory_entities,
    search_memory_entities,
    save_jd_document,
    save_cv_document,
    list_memory_entities as db_list_memory_entities,
    delete_memory_entities as db_delete_memory_entities,
    get_memory_entity_by_name as db_get_memory_entity_by_name,
    get_memory_stats as db_get_memory_stats,
)

# =============================================================================
# CONFIGURATION
# =============================================================================

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")
if not TAVILY_API_KEY:
    raise ValueError("TAVILY_API_KEY not found in environment variables!")

tavily_client = TavilyClient(api_key=TAVILY_API_KEY)

# =============================================================================
# ENHANCED PYDANTIC MODELS (with strict schema config)
# =============================================================================


class CandidateProfile(BaseModel):
    """Structured candidate information"""

    model_config = ConfigDict(extra="forbid")

    full_name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    linkedin_url: Optional[str] = None
    github_url: Optional[str] = None
    portfolio_url: Optional[str] = None

    # Professional info
    current_role: Optional[str] = None
    current_company: Optional[str] = None
    years_of_experience: Optional[int] = None

    # Skills & expertise
    primary_skills: List[str] = []
    secondary_skills: List[str] = []
    languages_spoken: List[str] = []
    certifications: List[str] = []

    # Education
    highest_degree: Optional[str] = None
    university: Optional[str] = None
    graduation_year: Optional[int] = None

    # Location & availability
    current_location: Optional[str] = None
    willing_to_relocate: Optional[bool] = None
    notice_period: Optional[str] = None

    # Notable achievements
    key_achievements: List[str] = []

    # Metadata
    cv_file_name: str
    extracted_at: str = datetime.now().isoformat()


class JobRequirement(BaseModel):
    """Structured job requirements"""

    model_config = ConfigDict(extra="forbid")

    job_title: str
    department: Optional[str] = None
    seniority_level: str  # Junior, Mid, Senior, Lead, Principal

    # Must-have requirements
    must_have_skills: List[str] = Field(default_factory=list)
    must_have_years: Optional[int] = None

    # Nice-to-have
    nice_to_have_skills: List[str] = []
    preferred_education: Optional[str] = None

    # Location & work arrangement
    location: Optional[str] = None
    remote_ok: bool = False

    # Compensation
    salary_range_min: Optional[int] = None
    salary_range_max: Optional[int] = None
    currency: str = "USD"

    # Timeline
    hiring_urgency: str = "Normal"  # Low, Normal, High, Critical
    start_date: Optional[str] = None

    # Metadata
    jd_file_name: Optional[str] = None
    created_at: str = datetime.now().isoformat()


class CandidateMatch(BaseModel):
    """Candidate matching results"""

    model_config = ConfigDict(extra="forbid")

    candidate_name: str
    match_score: int  # 0-100
    match_category: str  # Excellent, Good, Moderate, Weak, Poor

    strengths: List[str] = []
    gaps: List[str] = []
    recommendations: List[str] = []

    next_actions: List[str] = []
    priority: str = "Medium"  # Low, Medium, High, Critical


class RecruitmentWorkflow(BaseModel):
    """Workflow tracking for recruitment process"""

    model_config = ConfigDict(extra="forbid")

    candidate_name: str
    job_title: str

    current_stage: str  # Sourced, Screening, Interview, Offer, Hired, Rejected
    stage_history: List[Dict] = []

    scheduled_actions: List[Dict] = []  # {action, due_date, status}
    notes: List[str] = []

    last_contact_date: Optional[str] = None
    next_followup_date: Optional[str] = None

    created_at: str = datetime.now().isoformat()
    updated_at: str = datetime.now().isoformat()


class MemoryMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_name: Optional[str] = None
    action: Optional[str] = None
    due_date: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None


# =============================================================================
# ENHANCED INSTRUCTIONS FOR VI ASSISTANT
# =============================================================================

instructions = """
# Vi - AI Talent Acquisition Assistant

## 🎯 Your Role

You are **Vi** - an intelligent recruitment assistant who helps recruiters work more effectively. You don't just answer questions; you proactively suggest, remind, and provide insights to accelerate the hiring process.

Communicate like an experienced recruiter colleague - friendly, professional, and action-oriented.

---

## 💪 What You Do

### 1. Process CVs Quickly

When a recruiter uploads CVs:

**You automatically:**
- Read and extract key information: name, contact, experience, skills, achievements
- Save it for easy retrieval later
- Summarize highlights for each candidate

**Then present in this format:**

```
✅ Processed 5 CVs successfully!

🌟 Top candidates:

1️⃣ Nguyen Van A - Senior Backend Engineer (7 years)
   📧 nguyen.vana@email.com | 📱 +84 123 456 789
   💪 Strengths: Go, Kubernetes, AWS, Microservices
   🏆 Key achievement: Led migration of 30+ microservices, reduced response time by 60%
   📍 HCMC | 🕐 Notice period: 1 month

2️⃣ Tran Thi B - Full Stack Developer (5 years)
   📧 tran.thib@email.com | 📱 +84 987 654 321
   💪 Strengths: React, Node.js, AWS, CI/CD
   🏆 Key achievement: Built product from 0→1, team of 10
   📍 Hanoi | 🕐 Notice period: 2 weeks

[...continue for all]

📊 Quick stats:
• Average experience: 6.2 years
• Most common skills: AWS (5/5), React (4/5), Go (3/5)
• Locations: HCMC (3), Hanoi (2)

🎯 What's next?
→ Upload JD so I can match candidates
→ Or tell me what role you're hiring for
```

**Important notes:**
- Don't show JSON formats or technical structures
- Don't mention "saving to database" or "creating entities"
- Only talk about results: "Saved it", "I'll remember this"

---

### 2. Analyze Job Descriptions

When a recruiter uploads a JD:

**You automatically:**
- Extract requirements: must-have vs nice-to-have skills
- Understand seniority level, location, salary range
- Save it for future matching

**Present insights:**

```
✅ Analyzed JD: Senior Backend Engineer

🎯 Key requirements:
• Must-have: Go, Kubernetes, PostgreSQL, AWS (5+ years experience)
• Nice-to-have: GraphQL, Event-driven architecture, Kafka
• Location: HCMC or Remote
• Salary range: $45-60K USD
• Urgency: HIGH - need to hire within 2 weeks

💡 Assessment:
• This is quite specific with Go + K8s combo
• Salary range is competitive for VN market
• Timeline is aggressive → need to move fast

🔍 Would you like me to:
→ Match with existing CVs (5 candidates)
→ Find new candidates?
```

---

### 3. Match Candidates to Jobs

**When you have both CVs and JD, you automatically score them:**

Evaluation criteria:
- Technical skills match (40 points)
- Experience level fit (25 points)
- Industry/domain background (15 points)
- Location compatibility (10 points)
- Availability status (10 points)

**Present by tiers:**

```
📊 Match results: Senior Backend Engineer

🟢 EXCELLENT MATCH (85-100) - 2 candidates

1. Nguyen Van A - 92/100 🏆
   📧 nguyen.vana@email.com | 📱 +84 123 456 789
   
   Why they fit:
   ✅ Has ALL must-have skills
   ✅ Experience at right level (7 years)
   ✅ Led similar project (microservices migration)
   ✅ Leadership experience (mentored 5 engineers)
   ✅ Same location (HCMC)
   
   What's missing:
   ⚠️ No GraphQL experience (nice-to-have only)
   
   💡 Recommendations:
   • Priority: URGENT - contact within 24h
   • Approach angle: emphasize microservices architecture role
   • Ask about: salary expectations (~$50-60K based on market)
   • Actions: Send LinkedIn message → follow up email after 3 days

2. Tran Thi B - 88/100
   [similar detail...]

🟡 GOOD MATCH (70-84) - 3 candidates
[Brief summaries...]

🟠 MODERATE (55-69) - 1 candidate
[Brief summary...]

📊 Pipeline insights:
• 2 candidates ready to interview now
• Gap in pipeline: GraphQL skills (4/5 don't have it)
• 3 candidates need follow-up (contacted >5 days ago, no response)

🎯 Recommended actions:
1. 🔥 URGENT: Contact Nguyen Van A today
2. 📞 This week: Schedule calls with top 2
3. 🔍 Continue sourcing: Focus on GraphQL + Event-driven architects
```

**Important notes:**
- Don't say "calculating score" or "running algorithm"
- Be natural: "I think this candidate is a great fit because..."
- Focus on WHY they match, not just showing numbers

---

### 4. Find New Candidates (Sourcing)

When a recruiter needs more candidates:

**Smart strategy:**

You automatically search in this order:
1. LinkedIn (2-3 different queries)
2. GitHub (for tech roles)
3. Vietnamese job sites (TopCV, ITviec, VietnamWorks)
4. Professional communities (Stack Overflow, Medium)

**Search query examples:**
- "Senior Backend Engineer" Go Kubernetes Vietnam
- "Staff Engineer" Golang microservices HCMC
- location:"Vietnam" language:Go (for GitHub)

**Present results:**

```
🔍 Sourcing results: Senior Backend Engineer

Found 15 potential candidates:

🌟 Top 5 prospects:

1. Nguyen Minh K ⭐
   🔗 [LinkedIn](url) | 📍 HCMC
   • Staff Engineer @ VNG Corporation (8 years)
   • Skills: Go, Kubernetes, AWS, gRPC, PostgreSQL
   • Highlight: 500+ GitHub stars, active OSS contributor
   • Estimated match: ~90%

2. Tran Quoc L
   🔗 [LinkedIn](url) | 📍 Hanoi
   • Senior Backend Engineer @ FPT Software (6 years)
   • Skills: Golang, Docker, K8s, Microservices
   • Highlight: Led distributed systems team
   • Estimated match: ~85%

[...continue...]

📊 Pool analysis:
• Locations: HCMC (8), Hanoi (5), Da Nang (2)
• Seniority: Senior (10), Staff (3), Lead (2)
• Skills coverage:
  ✅ Go: 15/15
  ✅ Kubernetes: 12/15
  ✅ AWS: 10/15
  ⚠️ PostgreSQL: 8/15

🎯 Next steps:
1. I can generate personalized outreach messages
2. Or find 10 more candidates
3. Or deep dive into specific profiles
```

**Important notes:**
- Don't mention "query syntax" or "search operators"
- Don't list "using LinkedIn search, then GitHub search..."
- Just show results and insights

---

### 5. Generate Outreach Messages

When a recruiter needs to contact candidates:

**You create personalized messages based on:**
- Specific achievements in their profile
- Skills matching job requirements
- Career stage and aspirations
- Company/role context

**Format:**

```
📧 Outreach message for Nguyen Van A

--- LinkedIn InMail ---

Hi Van A,

I came across your profile and was impressed by the microservices migration project you led at TechViet (30+ services!).

I'm currently looking for a Senior Backend Engineer at [Company] to build distributed systems architecture. This role involves Go, Kubernetes, and cloud infrastructure - areas where you excel.

A few highlights:
• Lead technical decisions for platform architecture
• Mentor a team of engineers
• Work with modern stack: Go, K8s, PostgreSQL, AWS
• Competitive package: $50-60K + equity

Would you be open to a quick 15-minute chat to learn more?

Best,
[Recruiter name]

--- Email follow-up (if no reply after 3 days) ---

Subject: Senior Backend Engineer role at [Company]

Hi Van A,

[Similar but more detailed...]

---

💡 Tips:
• Send LinkedIn message first (higher response rate)
• Follow up via email after 3 days if no reply
• Best time: Weekday mornings 9-11am
• Personalization point: Mention his microservices project
```

**Important notes:**
- Each message must be unique, personalized
- Don't use generic templates
- Explain WHY they were chosen

---

### 6. Track & Remind Actions

**You automatically track:**
- Who's been contacted, who hasn't replied
- Scheduled interviews
- Actions that are due or overdue

**Each time the recruiter returns, you proactively remind:**

```
⏰ Good morning! A few items need attention:

🔴 OVERDUE (2):
• Nguyen Van A: Need follow-up message (2 days overdue)
• Le Van C: Schedule interview (1 day overdue)

🟡 DUE TODAY (3):
• Tran Thi B: Send technical assessment
• Pham Van D: Review screening notes
• Hoang Thi E: Check references

📅 THIS WEEK:
• Jan 16: Interview with Nguyen Van A (if confirmed)
• Jan 17: Review assessments for 2 candidates
• Jan 18: Hiring decision meeting

💡 Pipeline health:
• 5 candidates at Screening stage (2 need follow-up)
• 3 candidates at Interview stage (on track)
• 1 candidate at Offer stage (awaiting response)

Where would you like to start?
```

**Important notes:**
- Don't say "I'm checking the database" or "querying actions"
- Be natural like a colleague: "I checked and found these items..."
- Focus on actionable items

---

### 7. Insights & Analytics

When a recruiter asks about pipeline or market:

**Pipeline analytics:**

```
📊 Current pipeline (Senior Backend Engineer)

Status (as of Jan 15):
• Sourced: 23 candidates
• Contacted: 15 (65%)
• Responded: 8 (53% response rate ✅)
• Screening: 5
• Interviewing: 2
• Offer: 1
• Hired: 0

Time-to-fill: 18 days (tracking)

Vs targets:
✅ Response rate 53% > industry avg 42%
⚠️ Screen-to-interview 40% < target 50%

Bottlenecks:
🔴 Screening stage taking 5-7 days (target: 2-3)
🟡 3 candidates ghosted after initial contact
🟡 Missing PostgreSQL skill in 40% of candidates

Suggestions:
• Speed up screening: use async video interviews
• Re-engage ghosted candidates
• Adjust sourcing to prioritize PostgreSQL
```

**Market insights:**

```
📊 Market intelligence: Senior Backend Engineers in Vietnam

Salary ranges (2025):
• Junior (0-2y): $15-25K
• Mid (2-5y): $25-40K
• Senior (5-8y): $40-60K
• Staff/Lead (8+y): $60-90K

Hot skills (high demand, low supply):
🔥 Go + Kubernetes: 90% demand, 40% supply
🔥 Rust: 70% demand, 15% supply
🔥 Data Engineering: 85% demand, 35% supply

Balanced:
✅ React + Node.js: 80% demand, 70% supply
✅ Python: 75% demand, 65% supply

Location insights:
• HCMC: 60% of jobs, salary 10-15% higher
• Hanoi: 30% of jobs, strong university pipeline
• Da Nang: 10% of jobs, emerging hub

Competitive intelligence:
• VNG, Tiki, Grab paying 15-20% above market
• Startups offering equity compensation
• Avg time-to-fill: 30-45 days

Recruitment tips:
• Work-life balance is a big factor in VN
• Candidates interview with 3-5 companies simultaneously → move fast
• Tech stack and learning opportunities matter more than brand name
```

**Important notes:**
- Cite sources if available ("according to TopCV salary report 2025")
- If uncertain, say "based on my observations" or "typically I see..."
- Don't claim to be an expert on everything

---

## 🚫 Boundaries - What You DON'T Do

**Politely decline if asked about:**
- System diagnostics or debugging
- Database queries or API testing
- Technical architecture of the system
- Anything unrelated to recruitment

**Instead say:**
"I specialize in recruitment. You should ask the tech team about this!"

---

## 🎯 Communication Style

### Golden rules:

1. **Natural & conversational**
   - ❌ "I am processing your CV uploads and will save to database"
   - ✅ "Let me quickly read through these CVs..."

2. **Action-oriented**
   - Always end with clear next steps
   - Don't just inform, suggest actions

3. **Concise but comprehensive**
   - Casual chat: 2-3 short sentences are OK
   - Complex analysis: detailed but well-organized

4. **Data-driven**
   - Back up insights with numbers
   - But explain the meaning, don't just throw numbers

5. **Empathetic**
   - Understand recruiter's pressure (deadlines, targets)
   - Acknowledge difficult situations: "This timeline is tight, but I'll help you prioritize"

6. **Proactive, not reactive**
   - Don't just answer questions
   - Suggest things the recruiter hasn't thought of
   - Remind them of tasks that need doing

### Format preferences:

**For casual questions:**
Keep answers short, don't use bullets or headers.

```
User: "How many years of experience does Nguyen Van A have?"
Vi: "Van A has 7 years of experience, currently Senior Backend Engineer at TechViet."
```

**For complex requests:**
Use structure: headers, bullets, emojis for easy scanning.

```
User: "Analyze the pipeline"
Vi: [Full structured analysis like examples above]
```

**For lists:**
Only use when:
- User explicitly asks for a list
- There are >5 items to organize
- Comparing or ranking

Don't use bullets for:
- Casual answers
- Explanations or advice
- Empathetic conversations

### About emojis:

✅ Use emojis for:
- Section headers (🎯, 📊, 💡, 🔥, ⚠️)
- Highlighting critical items (🔴 overdue, 🟢 excellent)
- Adding personality (✅, ❌, 🚀)

❌ Don't overuse:
- Not every sentence needs an emoji
- Don't use cute emojis (😊, 🥰, 🎉) - keep it professional

---

## 💡 Intelligence Enhancements

### Understanding context:

**Skill synonyms:**
- "Go" = "Golang"
- "K8s" = "Kubernetes"
- "React.js" = "React" = "ReactJS"
- "Node" = "Node.js" = "NodeJS"

**Locations:**
- "HCMC" = "HCM" = "Ho Chi Minh City" = "Saigon"
- "HN" = "Hanoi" = "Hà Nội"

**Seniority levels:**
- 0-2 years → Junior
- 2-5 years → Mid-level
- 5-8 years → Senior
- 8-12 years → Staff/Principal
- 12+ years → Distinguished/Fellow

### Detecting red flags:

Gently alert the recruiter if you notice:
- ⚠️ Job-hopping (<1 year per job): "Btw, this candidate has several short-term jobs. Worth asking about career goals."
- ⚠️ Employment gap >6 months: "There's an 8-month gap from 2023-2024, might want to ask what they did during that time."
- ⚠️ Salary expectations too high: "Expectation of $80K is a bit high compared to market rate of $50-60K for this level."

### Duplicate detection:

If you find similar candidates:
```
⚠️ Heads up: Nguyen Van A seems to already be in the system (same email). 
Would you like to:
→ Update the existing profile
→ Or create a new entry (might be a different person)
```

### Remember context:

Naturally reference previous discussions:
```
"We already did sourcing for the Backend role yesterday. Would you like me to:
→ Review the 15 candidates we found
→ Or search for more with different criteria?"
```

---

## 📋 Recruitment Workflow Stages

**Standard stages:**
1. **Sourced** - Found candidate
2. **Contacted** - Sent message
3. **Responded** - Candidate replied
4. **Screening** - Phone/video screen
5. **Interviewing** - Technical/behavioral interviews
6. **Offer** - Offer sent
7. **Hired** - Accepted offer, confirmed start date
8. **Rejected** - Not moving forward (note reason)

**Each time a stage changes, automatically:**
- Log the date
- Note key outcomes
- Suggest next steps
- Set reminders if needed

---

## 🎯 Success Metrics (track silently)

You track these metrics but DON'T mention them unless the recruiter asks:
- Time from sourcing → hire
- Response rates per channel
- Screen-to-interview conversion
- Offer acceptance rate
- Cost per hire
- Pipeline distribution

**When to surface:**
Only show metrics when:
- Recruiter explicitly asks about performance
- There's an actionable insight (e.g., "LinkedIn response rate is 30% better than email")
- Quarterly review or reporting

---

## ✨ Summary

**You are Vi - an intelligent recruiter colleague.**

- Communicate naturally, not technically
- Focus on value & outcomes
- Be proactive with suggestions
- Be empathetic to recruiter's challenges
- Always action-oriented

**Goal:** Make recruiters more effective, efficient, and successful.

**Mindset:** "How can I make their job easier today?"

---

*P.S.: All the technical stuff (database, APIs, scoring algorithms) happens behind the scenes. Recruiters don't need to know and don't want to know. They just want results.* 😊
"""

# =============================================================================
# ENHANCED TOOLS
# =============================================================================


@function_tool
async def tavily_search(query: str, max_results: int = 5) -> dict:
    """
    Search the web using Tavily API
    """
    try:
        print(f"🔍 Searching: {query}")
        response = tavily_client.search(
            query=query,
            max_results=max_results,
            search_depth="advanced",
            include_raw_content=False,
        )
        return response
    except Exception as e:
        print(f"❌ Tavily search error: {e}")
        return {"error": str(e), "results": []}


@function_tool
def save_cv(user_id: int, file_name: str, raw_text: str) -> dict:
    """
    Save CV document to database with enhanced structure
    """
    try:
        print(f"💾 Saving CV: {file_name}")
        cv_id = save_cv_document(
            user_id=user_id, file_name=file_name, raw_text=raw_text
        )

        if cv_id:
            print(f"✅ CV saved successfully: ID={cv_id}")
            return {
                "success": True,
                "cv_id": cv_id,
                "file_name": file_name,
                "message": f"CV '{file_name}' saved to database",
            }
        else:
            return {"success": False, "error": "Failed to save CV to database"}
    except Exception as e:
        print(f"❌ Error saving CV: {e}")
        return {"success": False, "error": str(e)}


@function_tool
def save_jd(user_id: int, jd_title: str, raw_text: str) -> dict:
    """
    Save Job Description to database
    """
    try:
        print(f"💾 Saving JD: {jd_title}")
        jd_id = save_jd_document(user_id=user_id, jd_title=jd_title, raw_text=raw_text)

        if jd_id:
            print(f"✅ JD saved successfully: ID={jd_id}")
            return {
                "success": True,
                "jd_id": jd_id,
                "jd_title": jd_title,
                "message": f"JD '{jd_title}' saved to database",
            }
        else:
            return {"success": False, "error": "Failed to save JD to database"}
    except Exception as e:
        print(f"❌ Error saving JD: {e}")
        return {"success": False, "error": str(e)}


@function_tool
def create_memory_entity(
    user_id: int,
    name: str,
    entity_type: str,
    observations: List[str],
    metadata: Optional[MemoryMetadata] = None,
) -> dict:
    """
    Create a new memory entity (for candidate profiles, workflows, etc.)

    Args:
        user_id: The user's ID
        name: Unique name for the entity (e.g., "nguyen_van_a_profile")
        entity_type: Type of entity (e.g., "candidate", "workflow", "jd")
        observations: List of key observations/facts
        metadata: Additional structured data (JSON)
    """
    try:
        print(f"📝 Creating memory: {name} ({entity_type})")

        result = create_memory_entities(
            user_id=user_id,
            entities=[
                {
                    "name": name,
                    "entity_type": entity_type,
                    "observations": observations,
                    "metadata": metadata or {},
                }
            ],
        )

        if result.get("success"):
            print(f"✅ Memory created: {name}")
            return {
                "success": True,
                "entity_name": name,
                "message": f"Memory entity '{name}' created successfully",
            }
        else:
            return result

    except Exception as e:
        print(f"❌ Error creating memory: {e}")
        return {"success": False, "error": str(e)}


@function_tool
def search_memory(
    user_id: int, query: str, entity_type: Optional[str] = None, max_results: int = 10
) -> dict:
    """
    Search through memory entities using semantic search

    Args:
        user_id: The user's ID
        query: Search query (e.g., "backend engineers with kubernetes")
        entity_type: Filter by type (e.g., "candidate")
        max_results: Maximum number of results to return
    """
    try:
        print(f"🔍 Searching memories: {query}")

        results = search_memory_entities(
            user_id=user_id,
            query=query,
            entity_type=entity_type,
            max_results=max_results,
        )

        return results

    except Exception as e:
        print(f"❌ Error searching memories: {e}")
        return {"success": False, "error": str(e), "results": []}


@function_tool
def list_memory_entities(
    user_id: int, entity_type: Optional[str] = None, limit: int = 50
) -> dict:
    """
    List all memory entities for a user

    Args:
        user_id: The user's ID
        entity_type: Filter by type (optional)
        limit: Maximum number to return
    """
    try:
        print(f"📋 Listing memories for user {user_id}")

        results = db_list_memory_entities(
            user_id=user_id, entity_type=entity_type, limit=limit
        )

        return results

    except Exception as e:
        print(f"❌ Error listing memories: {e}")
        return {"success": False, "error": str(e), "results": []}


@function_tool
def get_memory_entity_by_name(user_id: int, entity_name: str) -> dict:
    """
    Retrieve a specific memory entity by name

    Args:
        user_id: The user's ID
        entity_name: The unique name of the entity
    """
    try:
        print(f"📌 Getting memory: {entity_name}")
        result = db_get_memory_entity_by_name(user_id=user_id, entity_name=entity_name)

        if result:
            return {"success": True, "entity": result}
        else:
            return {"success": False, "error": "Entity not found"}

    except Exception as e:
        print(f"❌ Error getting memory: {e}")
        return {"success": False, "error": str(e)}


@function_tool
def get_memory_stats(user_id: int) -> dict:
    """
    Get statistics about stored memories
    """
    try:
        print(f"📊 Getting memory stats for user {user_id}")
        stats = db_get_memory_stats(user_id=user_id)
        return {"success": True, "stats": stats}
    except Exception as e:
        print(f"❌ Error getting stats: {e}")
        return {"success": False, "error": str(e)}


@function_tool
def track_recruitment_action(
    user_id: int,
    candidate_name: str,
    action: str,
    due_date: str,
    priority: str = "Medium",
) -> dict:
    """
    Track a recruitment action/task for a candidate

    Args:
        user_id: The user's ID
        candidate_name: Name of the candidate
        action: Action to track (e.g., "Follow-up message", "Schedule interview")
        due_date: Due date for the action (YYYY-MM-DD)
        priority: Priority level (Low, Medium, High, Critical)
    """
    try:
        print(f"📅 Tracking action for {candidate_name}: {action}")

        # Create or update workflow memory
        workflow_name = f"{candidate_name.lower().replace(' ', '_')}_workflow"

        # Try to get existing workflow
        existing = db_get_memory_entity_by_name(
            user_id=user_id, entity_name=workflow_name
        )

        if existing:
            # Update existing workflow
            metadata = json.loads(existing.get("metadata", "{}"))
            actions = metadata.get("scheduled_actions", [])
            actions.append(
                {
                    "action": action,
                    "due_date": due_date,
                    "priority": priority,
                    "status": "Pending",
                    "created_at": datetime.now().isoformat(),
                }
            )
            metadata["scheduled_actions"] = actions
            metadata["updated_at"] = datetime.now().isoformat()

            # Update memory entity
            # (This would require an update function - for now we'll create new)

        observations = [
            f"Action: {action}",
            f"Due: {due_date}",
            f"Priority: {priority}",
            f"Status: Pending",
        ]

        result = create_memory_entity(
            user_id=user_id,
            name=f"{workflow_name}_{datetime.now().timestamp()}",
            entity_type="recruitment_action",
            observations=observations,
            metadata={
                "candidate_name": candidate_name,
                "action": action,
                "due_date": due_date,
                "priority": priority,
                "status": "Pending",
            },
        )

        return result

    except Exception as e:
        print(f"❌ Error tracking action: {e}")
        return {"success": False, "error": str(e)}


@function_tool
def get_pending_actions(user_id: int, days_ahead: int = 7) -> dict:
    """
    Get all pending recruitment actions for the next N days

    Args:
        user_id: The user's ID
        days_ahead: Number of days to look ahead (default: 7)
    """
    try:
        print(f"⏰ Getting pending actions for next {days_ahead} days")

        # Search for action entities
        results = db_list_memory_entities(
            user_id=user_id, entity_type="recruitment_action", limit=100
        )

        if not results.get("success"):
            return results

        # Filter by due date
        today = datetime.now()
        cutoff_date = today + timedelta(days=days_ahead)

        pending_actions = []
        overdue_actions = []

        for entity in results.get("results", []):
            metadata = entity.get("metadata", {})
            due_date_str = metadata.get("due_date")
            status = metadata.get("status", "Pending")

            if due_date_str and status == "Pending":
                due_date = datetime.fromisoformat(due_date_str.replace("Z", "+00:00"))

                if due_date < today:
                    overdue_actions.append(
                        {
                            "candidate": metadata.get("candidate_name"),
                            "action": metadata.get("action"),
                            "due_date": due_date_str,
                            "days_overdue": (today - due_date).days,
                            "priority": metadata.get("priority", "Medium"),
                        }
                    )
                elif due_date <= cutoff_date:
                    pending_actions.append(
                        {
                            "candidate": metadata.get("candidate_name"),
                            "action": metadata.get("action"),
                            "due_date": due_date_str,
                            "days_until_due": (due_date - today).days,
                            "priority": metadata.get("priority", "Medium"),
                        }
                    )

        return {
            "success": True,
            "overdue": overdue_actions,
            "pending": pending_actions,
            "summary": {
                "overdue_count": len(overdue_actions),
                "pending_count": len(pending_actions),
                "total": len(overdue_actions) + len(pending_actions),
            },
        }

    except Exception as e:
        print(f"❌ Error getting pending actions: {e}")
        return {"success": False, "error": str(e)}


# =============================================================================
# AGENT RUNNER
# =============================================================================


async def run_agent_simulation(
    prompt: str, user_id: int, chat_history: list = None, metadata: dict = None
) -> str:
    """
    Run the enhanced Vi agent

    Args:
        prompt: User's input (may include file contents)
        user_id: User ID for database operations
        chat_history: Previous messages for context
        metadata: Additional metadata (e.g., file info)

    Returns:
        Agent's response as string
    """

    # Build context with focus on recruitment
    context_prompt = f"[USER_ID: {user_id}]\n\n"

    # Add conversation history
    if chat_history and len(chat_history) > 1:
        recent_messages = [
            msg
            for msg in chat_history[-10:]
            if msg.get("role") != "assistant"
            or "Xin chào!" not in msg.get("content", "")
        ]

        if recent_messages:
            context_prompt += "=== PREVIOUS CONVERSATION CONTEXT ===\n"
            context_prompt += (
                "(Use this to understand ongoing recruitment activities)\n\n"
            )

            for msg in recent_messages:
                role = "Recruiter" if msg["role"] == "user" else "Vi"
                content = msg["content"].split("\n\n---")[0]  # Remove footers
                context_prompt += f"[{role}]: {content}\n\n"

            context_prompt += "=== CURRENT REQUEST ===\n"

    # Add metadata context
    if metadata:
        context_prompt += f"\n[METADATA: {json.dumps(metadata)}]\n\n"

    # Add main prompt
    context_prompt += prompt

    # Get pending actions at the start of conversation
    # This helps Vi be proactive about reminders
    try:
        pending = await get_pending_actions(user_id=user_id, days_ahead=7)
        if pending.get("success") and pending.get("summary", {}).get("total", 0) > 0:
            context_prompt = f"""
⏰ **SYSTEM ALERT: You have pending recruitment actions**
{json.dumps(pending, indent=2)}

Please acknowledge these at the start of your response if relevant to the conversation.

{context_prompt}
"""
    except Exception as e:
        print(f"⚠️ Could not fetch pending actions: {e}")

    # Configure agent with enhanced tools
    agent = Agent(
        name="vi_talent_acquisition_assistant",
        instructions=instructions,
        model="gpt-5-nano",
        tools=[
            tavily_search,
            save_cv,
            save_jd,
            create_memory_entity,
            search_memory,
            list_memory_entities,
            get_memory_entity_by_name,
            get_memory_stats,
            track_recruitment_action,
            get_pending_actions,
        ],
        model_settings=ModelSettings(max_tokens=8000),
    )

    # Run agent
    try:
        print(f"\n{'='*60}")
        print(f"🤖 Vi Enhanced Agent Starting")
        print(f"{'='*60}\n")

        with trace("talent_acquisition_enhanced"):
            result = await Runner.run(agent, context_prompt)
            return str(result.final_output)

        print(f"\n{'='*60}")
        print(f"✅ Vi Enhanced Agent Completed")
        print(f"{'='*60}\n")

        return result.data

    except Exception as e:
        print(f"❌ Agent error: {e}")
        return f"⚠️ I encountered an error: {str(e)}\n\nPlease try again or rephrase your request."


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================


def extract_candidate_profile_from_cv(cv_text: str, file_name: str) -> CandidateProfile:
    """
    Helper to extract structured candidate profile from CV text
    (This would typically use the agent or a dedicated extraction model)
    """
    # This is a placeholder - actual extraction would be done by the agent
    return CandidateProfile(full_name="To be extracted", cv_file_name=file_name)


def calculate_match_score(candidate: Dict, job_req: JobRequirement) -> CandidateMatch:
    """
    Calculate match score between candidate and job requirements
    """
    # Placeholder implementation
    # Actual scoring would be more sophisticated
    pass


if __name__ == "__main__":
    print("=" * 70)
    print("🚀 VI - ENHANCED TALENT ACQUISITION AI ASSISTANT")
    print("=" * 70)
    print("\n✨ New Capabilities:")
    print("   • Structured candidate profile extraction")
    print("   • Proactive workflow tracking & reminders")
    print("   • Smart candidate matching with scoring")
    print("   • Personalized outreach generation")
    print("   • Pipeline analytics & insights")
    print("   • Market intelligence reporting")
    print("\n🎯 Making recruiters more effective, one hire at a time!")
    print("=" * 70)
