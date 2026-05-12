# Socra - AI Tutoring Platform MVP Scope

> **Tagline**: "Your tutor, your materials" — Learn through Socratic dialogue using your own course PDFs.

---

## Project Context

- **Academic**: EMSI 4AISDR course project on Multi-Agent Systems (SMA) and Agentic AI
- **Product**: Functional MVP for university students to learn via Socratic dialogue
- **Developer**: Solo
- **Timeline**: 4 weeks

---

## Core Value Proposition

Unlike generic AI tutors (like hisocra.com), Socra teaches from **the student's actual course materials**:
- Upload your professor's lecture slides
- Upload your specific textbook chapters
- Get answers that cite page numbers from YOUR documents
- Tutor uses YOUR course's terminology and emphasis

---

## MVP Features (What We're Building)

### 1. Landing Page
- Hero section with tagline
- Feature highlights
- Sign up / Login CTAs
- Dark academic aesthetic

### 2. Authentication
- Email/password signup
- Email/password login
- Session management
- Protected routes

### 3. Dashboard
- List of user's courses
- Create new course button
- Course cards with metadata

### 4. PDF Upload System
- Drag-and-drop upload modal
- Upload progress indicator
- Store PDFs in Supabase Storage
- Chunk and embed PDFs for RAG
- Store embeddings in pgvector

### 5. Chat Interface (3-Panel Layout)
- **Left Sidebar**: Course name, PDF list, recent inquiries
- **Center Panel**: Streaming Socratic chat
- **Right Panel**: Key terms, suggested reading

### 6. Socratic Dialogue Engine
- Never gives direct answers
- Always asks what the student thinks first
- Identifies misconceptions through questioning
- References specific sections from uploaded materials

### 7. Session Persistence
- Save conversations to database
- Load conversation history
- Resume previous sessions

---

## Explicitly NOT in MVP

- Cross-session memory ("Last week you struggled with X")
- Spaced repetition / quiz scheduling
- Prerequisite/knowledge graph
- Mobile apps
- Voice input/output
- Collaborative features
- Goal-setting flow (like hisocra.com)

---

## Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| Frontend | Next.js 14+ (App Router) | React framework with SSR |
| Styling | Tailwind CSS + shadcn/ui | UI components |
| Fonts | Newsreader (serif) + Manrope (sans) | Typography |
| Auth | Supabase Auth | User authentication |
| Database | Supabase PostgreSQL | Relational data |
| Vector DB | Supabase pgvector | Embedding storage |
| File Storage | Supabase Storage | PDF files |
| AI SDK | Vercel AI SDK | Streaming, tool calling |
| LLM | Gemini (Google) | Socratic dialogue |
| Embeddings | Gemini text-embedding-004 | Document embeddings (768-dim) |
| PDF Processing | pdf-parse + LangChain | Chunking |
| Deployment | Vercel | Hosting |

---

## Design System

### Colors
```css
--primary: #1A2634;    /* Deep navy */
--secondary: #8DA399;  /* Sage green */
--tertiary: #D4A373;   /* Warm amber */
--neutral: #121417;    /* Near black */
```

### Typography
- **Headings**: Newsreader (serif) - academic, thoughtful
- **Body**: Manrope (sans-serif) - clean, readable
- **Tutor messages**: Newsreader italic for Socratic questions

### Theme
- Dark mode by default
- Light mode toggle available

---

## Database Schema

### Tables

```sql
-- courses: Groups of uploaded materials
CREATE TABLE courses (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth.users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  description TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- documents: Individual PDF files
CREATE TABLE documents (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  course_id UUID REFERENCES courses(id) ON DELETE CASCADE,
  filename TEXT NOT NULL,
  storage_path TEXT NOT NULL,
  page_count INTEGER,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- embeddings: Chunked document content with vectors
CREATE TABLE embeddings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  embedding VECTOR(1536),
  metadata JSONB DEFAULT '{}'::jsonb,
  page_number INTEGER,
  chunk_index INTEGER
);

-- sessions: Chat conversations
CREATE TABLE sessions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  course_id UUID REFERENCES courses(id) ON DELETE CASCADE,
  title TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  updated_at TIMESTAMPTZ DEFAULT now()
);

-- messages: Individual chat messages
CREATE TABLE messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
  content TEXT NOT NULL,
  metadata JSONB DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- key_terms: Extracted terms from conversations
CREATE TABLE key_terms (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id UUID REFERENCES sessions(id) ON DELETE CASCADE,
  term TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);
```

### Functions

```sql
-- Similarity search for RAG
CREATE OR REPLACE FUNCTION match_embeddings(
  query_embedding VECTOR(1536),
  match_count INT,
  filter_course_id UUID
)
RETURNS TABLE (
  id UUID,
  content TEXT,
  document_id UUID,
  page_number INTEGER,
  similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    e.id,
    e.content,
    e.document_id,
    e.page_number,
    1 - (e.embedding <=> query_embedding) AS similarity
  FROM embeddings e
  JOIN documents d ON e.document_id = d.id
  WHERE d.course_id = filter_course_id
  ORDER BY e.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;
```

### Row Level Security (RLS)

```sql
-- Enable RLS on all tables
ALTER TABLE courses ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE embeddings ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE key_terms ENABLE ROW LEVEL SECURITY;

-- Users can only access their own courses
CREATE POLICY "Users can CRUD own courses" ON courses
  FOR ALL USING (auth.uid() = user_id);

-- Documents inherit from course ownership
CREATE POLICY "Users can CRUD own documents" ON documents
  FOR ALL USING (
    course_id IN (SELECT id FROM courses WHERE user_id = auth.uid())
  );

-- Similar policies for other tables...
```

---

## Folder Structure

```
socra/
├── app/
│   ├── (auth)/
│   │   ├── login/
│   │   │   └── page.tsx
│   │   └── signup/
│   │       └── page.tsx
│   │
│   ├── (dashboard)/
│   │   ├── layout.tsx
│   │   ├── page.tsx
│   │   │
│   │   └── course/
│   │       └── [courseId]/
│   │           ├── page.tsx
│   │           └── inquiry/
│   │               └── [sessionId]/
│   │                   └── page.tsx
│   │
│   ├── api/
│   │   ├── chat/
│   │   │   └── route.ts
│   │   ├── upload/
│   │   │   └── route.ts
│   │   ├── courses/
│   │   │   └── route.ts
│   │   └── context/
│   │       └── route.ts
│   │
│   ├── globals.css
│   ├── layout.tsx
│   └── page.tsx                    # Landing page
│
├── components/
│   ├── landing/
│   │   ├── Hero.tsx
│   │   ├── Features.tsx
│   │   └── CTA.tsx
│   │
│   ├── layout/
│   │   ├── Navbar.tsx
│   │   ├── Sidebar.tsx
│   │   └── ThemeToggle.tsx
│   │
│   ├── chat/
│   │   ├── ChatPanel.tsx
│   │   ├── MessageList.tsx
│   │   ├── Message.tsx
│   │   ├── TutorMessage.tsx
│   │   ├── StudentMessage.tsx
│   │   └── ChatInput.tsx
│   │
│   ├── context-panel/
│   │   ├── ContextPanel.tsx
│   │   ├── KeyTerms.tsx
│   │   ├── SuggestedReading.tsx
│   │   └── KnowledgeGraph.tsx      # Placeholder
│   │
│   ├── course/
│   │   ├── CourseCard.tsx
│   │   ├── CourseList.tsx
│   │   └── CreateCourseModal.tsx
│   │
│   ├── documents/
│   │   ├── DocumentList.tsx
│   │   ├── DocumentItem.tsx
│   │   └── UploadModal.tsx
│   │
│   ├── auth/
│   │   ├── LoginForm.tsx
│   │   └── SignupForm.tsx
│   │
│   └── ui/                         # shadcn/ui components
│       ├── button.tsx
│       ├── input.tsx
│       ├── card.tsx
│       ├── dialog.tsx
│       ├── badge.tsx
│       ├── avatar.tsx
│       ├── dropdown-menu.tsx
│       ├── scroll-area.tsx
│       └── skeleton.tsx
│
├── lib/
│   ├── supabase/
│   │   ├── client.ts               # Browser client
│   │   ├── server.ts               # Server client
│   │   └── middleware.ts           # Auth middleware
│   │
│   ├── ai/
│   │   ├── socratic-prompt.ts      # Core system prompt
│   │   ├── rag.ts                  # Retrieval logic
│   │   └── extract-terms.ts        # Key term extraction
│   │
│   ├── pdf/
│   │   ├── parser.ts               # PDF text extraction
│   │   └── chunker.ts              # Text chunking
│   │
│   ├── embeddings/
│   │   └── generate.ts             # OpenAI embedding calls
│   │
│   └── utils.ts                    # Helpers
│
├── hooks/
│   ├── useChat.ts
│   ├── useUpload.ts
│   ├── useCourses.ts
│   ├── useSession.ts
│   └── useContextPanel.ts
│
├── types/
│   ├── index.ts
│   ├── database.ts                 # Supabase generated types
│   └── api.ts
│
├── public/
│   ├── fonts/
│   │   ├── Newsreader/
│   │   └── Manrope/
│   └── images/
│       └── logo.svg
│
├── middleware.ts                   # Auth route protection
├── .env.local
├── .env.example
├── tailwind.config.ts
├── next.config.js
├── package.json
├── tsconfig.json
└── README.md
```

---

## Environment Variables

```env
# Supabase
NEXT_PUBLIC_SUPABASE_URL=your_supabase_url
NEXT_PUBLIC_SUPABASE_ANON_KEY=your_anon_key
SUPABASE_SERVICE_ROLE_KEY=your_service_role_key

# AI APIs
ANTHROPIC_API_KEY=your_anthropic_key
GEMINI_API_KEY=your_gemini_key

# App
NEXT_PUBLIC_APP_URL=http://localhost:3000
```

---

## Detailed Task Breakdown

### Phase 1: Project Setup (Week 1, Days 1-2)

#### 1.1 Initialize Next.js Project
- [x] Create Next.js 14 project with TypeScript
- [x] Configure App Router
- [x] Set up path aliases in tsconfig.json
- [x] Create folder structure

#### 1.2 Configure Tailwind CSS
- [x] Install Tailwind CSS
- [x] Configure tailwind.config.ts with custom colors
- [x] Set up CSS variables in globals.css
- [x] Configure dark mode (class strategy)

#### 1.3 Set Up Fonts
- [x] Download Newsreader font files
- [x] Download Manrope font files
- [x] Configure next/font local fonts
- [x] Define font CSS variables

#### 1.4 Install shadcn/ui
- [x] Initialize shadcn/ui
- [x] Configure components.json
- [x] Install base components: button, input, card, dialog, badge
- [x] Install additional: avatar, dropdown-menu, scroll-area, skeleton

#### 1.5 Create Base Layout
- [x] Create root layout.tsx with fonts and theme
- [x] Create globals.css with design tokens
- [x] Set up metadata (title, description, icons)

---

### Phase 2: Supabase Setup (Week 1, Days 2-3)

#### 2.1 Create Supabase Project
- [x] Create new project in Supabase dashboard
- [x] Note project URL and keys
- [x] Enable pgvector extension

#### 2.2 Set Up Environment Variables
- [x] Create .env.local file
- [x] Add Supabase URL
- [x] Add Supabase anon key
- [x] Add Supabase service role key
- [x] Create .env.example template

#### 2.3 Create Database Schema
- [x] Create courses table
- [x] Create documents table
- [x] Create embeddings table with vector column
- [x] Create sessions table
- [x] Create messages table
- [x] Create key_terms table

#### 2.4 Set Up Row Level Security
- [x] Enable RLS on courses table
- [x] Create courses RLS policy
- [x] Enable RLS on documents table
- [x] Create documents RLS policy
- [x] Enable RLS on embeddings table
- [x] Create embeddings RLS policy
- [x] Enable RLS on sessions table
- [x] Create sessions RLS policy
- [x] Enable RLS on messages table
- [x] Create messages RLS policy
- [x] Enable RLS on key_terms table
- [x] Create key_terms RLS policy

#### 2.5 Create Database Functions
- [x] Create match_embeddings function for similarity search
- [x] Test function with sample data

#### 2.6 Configure Storage
- [x] Create 'documents' storage bucket
- [x] Set bucket to private
- [x] Create storage RLS policies

#### 2.7 Set Up Supabase Clients
- [x] Install @supabase/supabase-js
- [x] Install @supabase/ssr
- [x] Create lib/supabase/client.ts (browser)
- [x] Create lib/supabase/server.ts (server)
- [x] Create lib/supabase/middleware.ts

#### 2.8 Generate TypeScript Types
- [x] Install supabase CLI (used MCP instead)
- [x] Generate types from database schema
- [x] Save to types/database.ts

---

### Phase 3: Authentication (Week 1, Days 3-4)

#### 3.1 Configure Auth Settings
- [x] Enable email/password auth in Supabase
- [x] Configure email templates (optional)
- [x] Set up redirect URLs

#### 3.2 Create Auth Middleware
- [x] Create middleware.ts at project root
- [x] Configure protected routes
- [x] Configure public routes
- [x] Handle auth refresh

#### 3.3 Create Auth Components
- [x] Create components/auth/LoginForm.tsx
- [x] Create components/auth/SignupForm.tsx
- [x] Add form validation
- [x] Add error handling
- [x] Add loading states

#### 3.4 Create Auth Pages
- [x] Create app/(auth)/login/page.tsx
- [x] Create app/(auth)/signup/page.tsx
- [x] Style auth pages to match design
- [x] Add redirect after auth

#### 3.5 Create Auth Hooks
- [x] Create hook for getting current user
- [x] Create hook for sign out
- [x] Test auth flow end-to-end

---

### Phase 4: Landing Page (Week 1, Days 4-5)

#### 4.1 Create Landing Page Components
- [x] Create components/landing/Hero.tsx
- [x] Create components/landing/Features.tsx
- [x] Create components/landing/CTA.tsx (ContactCTA.tsx)

#### 4.2 Design Hero Section
- [x] Add logo/brand name
- [x] Add tagline: "Learn by thinking, not memorizing"
- [x] Add subtitle explaining value prop
- [x] Add "Get Started" button
- [x] Add "Learn More" button (Try Demo → signup)

#### 4.3 Design Features Section
- [x] Feature 1: Socratic Method explanation (Inquire)
- [x] Feature 2: Your Materials, Your Way (Upload)
- [x] Feature 3: Track Your Progress (Master)
- [x] Add icons for each feature

#### 4.4 Design CTA Section
- [x] Final call to action (Contact Us section)
- [x] Sign up button (replaced with contact form)
- [x] Footer with links

#### 4.5 Assemble Landing Page
- [x] Create app/page.tsx
- [x] Compose all sections
- [x] Add animations (optional)
- [x] Test responsive design

---

### Phase 5: Dashboard Layout (Week 1, Day 5 - Week 2, Day 1)

#### 5.1 Create Dashboard Layout
- [x] Create app/(dashboard)/layout.tsx
- [x] Add top navbar
- [x] Add container structure

#### 5.2 Create Navbar Component
- [x] Create components/layout/DashboardNavbar.tsx
- [x] Add logo
- [x] Add navigation links (Active Courses, Library, Notebook)
- [x] Add theme toggle
- [x] Add notifications icon (placeholder)
- [x] Add user avatar dropdown (initials from user's full_name)
- [x] Add sign out option

#### 5.3 Create Theme Toggle
- [x] Install next-themes (already installed)
- [x] Create ThemeProvider (already existed in providers.tsx)
- [x] Create ThemeToggle component
- [x] Add to navbar

#### 5.4 Create Dashboard Home Page
- [x] Create app/(dashboard)/dashboard/page.tsx (refactored)
- [x] Add "Create New Course" button
- [x] Add course list with cards (fetches from Supabase)
- [x] Add empty state placeholder

---

### Phase 6: Course Management (Week 2, Days 1-2)

#### 6.1 Create Course Components
- [x] Create components/course/CourseCard.tsx
- [x] Create components/course/CourseList.tsx
- [x] Create components/course/CreateCourseModal.tsx

#### 6.2 Design CourseCard
- [x] Course name display
- [x] Document count
- [x] Last accessed date
- [x] Click to enter course
- [x] Context menu with delete option

#### 6.3 Design CreateCourseModal
- [x] Course name input
- [x] Description input (optional)
- [x] Create button
- [x] Cancel button
- [x] Loading/error states

#### 6.4 Create Course API Routes
- [x] Create app/api/courses/route.ts
- [x] Implement GET (list user's courses)
- [x] Implement POST (create new course)
- [x] Create app/api/courses/[id]/route.ts
- [x] Implement DELETE (delete course)

#### 6.5 Create Course Hooks
- [x] Create hooks/useCourses.ts
- [x] Implement fetchCourses
- [x] Implement createCourse
- [x] Implement deleteCourse

#### 6.6 Wire Up Dashboard
- [x] Connect CourseList to API
- [x] Connect CreateCourseModal to API
- [x] Add loading states (skeleton cards)
- [x] Add empty state
- [x] Add toast notifications for create/delete

---

### Phase 7: PDF Upload System (Week 2, Days 2-4)

#### 7.1 Create Upload Components
- [x] Create components/documents/UploadModal.tsx
- [x] Create components/documents/DocumentList.tsx
- [x] Create components/documents/DocumentItem.tsx

#### 7.2 Design UploadModal
- [x] Drag and drop zone
- [x] File input fallback
- [x] File type validation (PDF only)
- [x] File size validation (50MB max)
- [x] Upload progress bar
- [x] Success/error states

#### 7.3 Create PDF Parser
- [x] Install pdf-parse
- [x] Create lib/pdf/parser.ts
- [x] Extract text from PDF (per-page)
- [x] Extract page count
- [x] Handle errors

#### 7.4 Create Text Chunker
- [x] Create lib/pdf/chunker.ts
- [x] Implement chunking strategy (by paragraph/section)
- [x] Set chunk size (1000 tokens)
- [x] Set overlap (200 tokens)
- [x] Preserve page numbers in metadata

#### 7.5 Create Embedding Generator
- [x] Install @google/generative-ai (switched from OpenAI to Gemini)
- [x] Create lib/embeddings/generate.ts
- [x] Implement batch embedding generation (text-embedding-004, 768-dim)
- [x] Updated database vectors from 1536 to 768 dimensions
- [x] Recreated match_embeddings function for 768-dim
- [x] Handle errors gracefully (document still saved if embedding fails)

#### 7.6 Create Upload API Route
- [x] Create app/api/upload/route.ts
- [x] Accept multipart form data
- [x] Upload file to Supabase Storage
- [x] Parse PDF to text
- [x] Chunk text
- [x] Generate embeddings
- [x] Store embeddings in pgvector
- [x] Create document record
- [x] Return success response
- [x] Create app/api/documents/[courseId]/route.ts (GET)
- [x] Create app/api/documents/delete/[id]/route.ts (DELETE)

#### 7.7 Create Upload Hook
- [x] Create hooks/useUpload.ts
- [x] Track upload progress
- [x] Handle errors

#### 7.8 Create Course Detail Page
- [x] Create app/(dashboard)/dashboard/course/[courseId]/page.tsx
- [x] Display course info
- [x] Display document list with delete
- [x] Add upload button + upload modal
- [x] Add "New Inquiry" button (disabled until documents exist)
- [x] Course stats sidebar (doc count, total pages, created date)

---

### Phase 8: Chat Interface UI (Week 2, Day 4 - Week 3, Day 2)

#### 8.1 Create Chat Layout
- [x] Create app/(dashboard)/course/[courseId]/inquiry/[sessionId]/page.tsx
- [x] Set up 3-panel grid layout
- [x] Make responsive (stack on mobile)

#### 8.2 Create Sidebar Component
- [x] Create components/layout/Sidebar.tsx
- [x] Course name header
- [x] Academic year display
- [x] "New Inquiry" button
- [x] Resources (PDFs) section
- [x] Document list with icons
- [x] Recent Inquiries section
- [x] Inquiry list with icons
- [x] Settings link
- [x] Support link

#### 8.3 Create Chat Panel Components
- [x] Create components/chat/ChatPanel.tsx
- [x] Create components/chat/MessageList.tsx
- [x] Create components/chat/Message.tsx
- [x] Create components/chat/TutorMessage.tsx
- [x] Create components/chat/StudentMessage.tsx
- [x] Create components/chat/ChatInput.tsx

#### 8.4 Design TutorMessage
- [x] Avatar icon
- [x] "SOCRA TUTOR" label
- [x] Message content with serif font
- [x] Italic styling for questions
- [x] Timestamp (optional)

#### 8.5 Design StudentMessage
- [x] "YOU" label
- [x] Right-aligned bubble
- [x] Different background color
- [x] Message content

#### 8.6 Design ChatInput
- [x] Input field with placeholder "Ask your tutor..."
- [x] Attachment icon (future feature)
- [x] Microphone icon (disabled, placeholder)
- [x] Send button
- [x] Handle Enter key
- [x] Disabled state while sending

#### 8.7 Design MessageList
- [x] Scrollable container
- [x] Auto-scroll to bottom on new messages
- [x] Loading skeleton while fetching
- [x] Empty state for new sessions

#### 8.8 Create Context Panel Components
- [x] Create components/context-panel/ContextPanel.tsx
- [x] Create components/context-panel/KeyTerms.tsx
- [x] Create components/context-panel/SuggestedReading.tsx
- [x] Create components/context-panel/KnowledgeGraph.tsx

#### 8.9 Design KeyTerms
- [x] "KEY TERMS IDENTIFIED" header
- [x] Badge/pill for each term
- [x] Grid layout for terms

#### 8.10 Design SuggestedReading
- [x] "SUGGESTED READING" header
- [x] Card with chapter info
- [x] Page number reference
- [x] Section description

#### 8.11 Design KnowledgeGraph Placeholder
- [x] "KNOWLEDGE GRAPH" header
- [x] Placeholder visual
- [x] "Synthesizing Insight" text
- [x] Loading animation

---

### Phase 9: Socratic Dialogue Engine (Week 3, Days 2-4)

#### 9.1 Create Socratic System Prompt
- [x] Create lib/ai/socratic-prompt.ts
- [x] Define tutor personality
- [x] Define Socratic rules:
  - [x] Never give direct answers
  - [x] Always ask what student thinks first
  - [x] Identify misconceptions
  - [x] Ask revealing questions
  - [x] Push deeper when correct
- [x] Define how to use context
- [x] Define response format
- [ ] Test prompt in Claude directly

#### 9.2 Create RAG Retrieval
- [x] Create lib/ai/rag.ts
- [x] Implement query embedding
- [x] Implement similarity search
- [x] Format context for prompt
- [x] Include source references (page numbers)

#### 9.3 Create Chat API Route
- [x] Install ai package (Vercel AI SDK)
- [x] Install @ai-sdk/google (using Gemini instead of Claude)
- [x] Create app/api/chat/route.ts
- [x] Accept messages array
- [x] Accept courseId
- [x] Retrieve relevant context via RAG
- [x] Inject context into system prompt
- [x] Stream response from Gemini
- [x] Return streaming response

#### 9.4 Create Key Term Extraction
- [x] Create lib/ai/extract-terms.ts
- [x] Define extraction prompt
- [x] Extract terms from conversation
- [x] Return as array

#### 9.5 Create Context API Route
- [x] Create app/api/context/route.ts
- [x] Accept session messages
- [x] Extract key terms
- [x] Find suggested readings from RAG
- [x] Return context data

#### 9.6 Create Chat Hook
- [x] Using Vercel AI SDK v6 useChat from @ai-sdk/react
- [x] Configure API endpoint via DefaultChatTransport
- [x] Handle streaming
- [x] Handle errors

#### 9.7 Create Context Panel Hook
- [x] Context updates integrated into inquiry page
- [x] Fetch context on message change
- [x] Update key terms
- [x] Update suggested reading

---

### Phase 10: Session Persistence (Week 3, Day 4 - Week 4, Day 1)

#### 10.1 Create Session Management
- [x] Create API for creating new session
- [x] Create API for fetching session
- [x] Create API for listing sessions
- [x] Create API for updating session title

#### 10.2 Create Message Persistence
- [x] Save user messages to database
- [x] Save assistant messages to database
- [x] Load messages on session open

#### 10.3 Create Session Hook
- [x] Create hooks/useSession.ts
- [x] Implement createSession
- [x] Implement loadSession
- [x] Implement saveMessage

#### 10.4 Wire Up Session to Chat
- [x] Create session on "New Inquiry" click
- [x] Save messages after each exchange (via onFinish in chat API)
- [x] Load existing messages on page load
- [x] Update session timestamp

#### 10.5 Update Sidebar with Sessions
- [x] Fetch recent sessions
- [x] Display in sidebar
- [x] Navigate to session on click
- [x] Show active session indicator

---

### Phase 11: Integration & Polish (Week 4, Days 1-3)

#### 11.1 Connect All Components
- [x] Wire sidebar to real data
- [x] Wire chat to API
- [x] Wire context panel to API
- [x] Wire document list to real data

#### 11.2 Add Loading States
- [x] Skeleton for course list
- [x] Skeleton for document list
- [x] Skeleton for message list
- [x] Skeleton for context panel
- [x] Loading spinner for uploads

#### 11.3 Add Error Handling
- [x] Error boundary component
- [x] Toast notifications for errors
- [x] Retry mechanisms (chat retry via regenerate)
- [x] Graceful degradation (RAG, embeddings fail gracefully)

#### 11.4 Add Empty States
- [x] No courses yet
- [x] No documents in course
- [x] No sessions yet
- [x] No key terms identified

#### 11.5 Responsive Design
- [x] Mobile nav menu (Sheet)
- [x] Collapse sidebar on mobile (toggle button)
- [x] Collapse context panel on tablet (toggle button)
- [x] Touch-friendly inputs

#### 11.6 Performance Optimization
- [x] Add React Suspense boundaries (dashboard layout)
- [x] Lazy load ChatPanel and ContextPanel
- [x] Suspense fallbacks with skeletons
- [x] Streaming responses (no full-response wait)

---

### Phase 12: Testing & Deployment (Week 4, Days 3-5)

#### 12.1 Manual Testing
- [ ] Test signup flow
- [ ] Test login flow
- [ ] Test logout flow
- [ ] Test course creation
- [ ] Test PDF upload (small file)
- [ ] Test PDF upload (large file)
- [ ] Test chat streaming
- [ ] Test Socratic responses
- [ ] Test context panel updates
- [ ] Test session persistence
- [ ] Test session resume

#### 12.2 Fix Bugs
- [ ] Document all bugs found
- [ ] Prioritize by severity
- [ ] Fix critical bugs
- [ ] Fix major bugs
- [ ] Document known issues

#### 12.3 Deployment Setup
- [ ] Create Vercel account (if needed)
- [ ] Connect GitHub repository
- [ ] Configure environment variables
- [ ] Configure build settings

#### 12.4 Deploy to Vercel
- [ ] Push to main branch
- [ ] Verify build succeeds
- [ ] Test deployed application
- [ ] Fix any deployment issues

#### 12.5 Production Testing
- [ ] Test with real course materials
- [ ] Test with multiple users
- [ ] Monitor for errors
- [ ] Check performance

---

### Phase 13: Documentation (Week 4, Day 5)

#### 13.1 Create README
- [ ] Project description
- [ ] Features list
- [ ] Tech stack
- [ ] Setup instructions
- [ ] Environment variables
- [ ] Development commands
- [ ] Deployment instructions

#### 13.2 Code Comments
- [ ] Document complex functions
- [ ] Document API routes
- [ ] Document hooks
- [ ] Document components (props)

#### 13.3 Academic Report (for EMSI)
- [ ] Architecture overview
- [ ] Agent mapping (SMA requirements)
- [ ] Technical choices justification
- [ ] Screenshots
- [ ] Future improvements

---

## API Endpoints Summary

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /api/auth/signup | Create new user |
| POST | /api/auth/login | Sign in user |
| POST | /api/auth/logout | Sign out user |
| GET | /api/courses | List user's courses |
| POST | /api/courses | Create new course |
| DELETE | /api/courses/[id] | Delete course |
| POST | /api/upload | Upload and process PDF |
| GET | /api/documents/[courseId] | List course documents |
| DELETE | /api/documents/[id] | Delete document |
| POST | /api/chat | Streaming chat endpoint |
| GET | /api/sessions/[courseId] | List course sessions |
| POST | /api/sessions | Create new session |
| GET | /api/sessions/[id]/messages | Get session messages |
| POST | /api/context | Get key terms + suggested reading |

---

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| PDF parsing fails | Use fallback parser, show error gracefully |
| Embedding costs too high | Start with smaller chunks, monitor usage |
| Claude responses not Socratic enough | Iterate on system prompt, add examples |
| Supabase free tier limits | Monitor usage, optimize queries |
| Large PDFs timeout | Process in chunks, use background jobs |

---

## Success Metrics (MVP)

- [ ] User can sign up and log in
- [ ] User can create a course
- [ ] User can upload a PDF
- [ ] User can start a chat
- [ ] Chat responses are Socratic (not direct answers)
- [ ] Context panel shows relevant terms
- [ ] Suggested reading references actual uploaded content
- [ ] Conversations persist across page refreshes
- [ ] Application is deployed and accessible

---

## Post-MVP Roadmap (Future)

1. **Goal-setting flow** - "What do you want to understand today?"
2. **Knowledge artifacts** - Export study guides, summaries
3. **Spaced repetition** - Schedule concept reviews
4. **Knowledge graph** - Visual prerequisite mapping
5. **Voice input** - Ask questions by speaking
6. **Mobile apps** - iOS and Android
7. **Collaboration** - Share courses with classmates
8. **Analytics** - Learning progress tracking

---

## Cursor MCP Plugins

### Already Installed
- **Supabase MCP** - Database management, SQL execution, docs search

### Recommended to Install
- **Vercel** - Deployment management
- **GitHub** - Repository management
- **Figma** - Import designs from Stitch

---

*Last updated: April 2026*
