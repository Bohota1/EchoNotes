Subject: EchoNotes – Project Brief

Hi [Teacher's Name],

Here's a short summary of our project, EchoNotes, for your reference.

EchoNotes is a voice note-taking app for blind and visually impaired students, based on the NexaNota research paper. Instead of typing, a student records a note out loud, and the app transcribes it, cleans up the text, and figures out what kind of note it is (a to-do, a brainstorm, academic content, etc.).

From there, it pulls out the topics a note covers and connects related topics into a knowledge graph, so notes on, say, Operating Systems automatically link to notes on Deadlocks or Process Scheduling without anyone organizing them by hand. Each topic also gets an auto-generated definition, example, and summary, while the student's original recording is always kept untouched alongside it.

Since the target users are blind or low vision, the whole app is built screen-reader-first — everything is read aloud as plain sentences rather than laid out only visually. We did add a couple of optional visual views (a diagram and a grouped "cluster" view of connected topics) for sighted reviewers, but they sit on top of the accessible version rather than replacing it.

Under the hood it's a FastAPI/SQLite backend with faster-whisper for speech-to-text, a React frontend, and an LLM used where it genuinely helps, with a rule-based fallback so the app keeps working even without one.

Happy to walk you through a live demo whenever suits you.

Best,
[Your names]
