"""Multi-tenant SaaS layer for the mobile Wingman app.

Activates when ``WINGMAN_MODE=saas``. In personal mode (default), this
package is dormant and the existing single-user pipeline runs as
before. The desktop app you've been using doesn't change.

The SaaS layer adds:
  • User accounts (email + password, JWT auth, ready for Apple/Google
    Sign In hooks)
  • Per-user data isolation (chats, examples, settings scoped by
    user_id under data/users/<user_id>/...)
  • Rate limiting + free-tier quota enforcement
  • A clean mobile-ready REST API surface, kept separate from the
    desktop UI's WebSocket protocol so the two can evolve independently
"""
import os

SAAS_MODE = (os.getenv("WINGMAN_MODE", "personal").strip().lower() == "saas")
