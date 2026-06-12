"""token_isolation.py — The paper's headline security story, simulated.

The AWS guidance's canonical example: an admin asks an agent to clone a
production database to pre-prod. The task needs only READ (to copy) and CREATE
(to make the target). If the agent's LLM hallucinates a "cleanup" step and the
system reused the admin's own credentials (which include DELETE), it would
delete production. With a purpose-generated, scoped-down token (READ + CREATE
only), the hallucinated DELETE FAILS SAFELY.

This simulates it against a mock "database service" with no real AWS resources.
It shows the same hallucinated workflow run under two tokens:

  - scoped_token   = {READ, CREATE}      -> clone succeeds, DELETE denied (safe)
  - admin_token    = {READ, CREATE, DELETE} -> DELETE would succeed (prod gone)

Run:
    python token_isolation.py
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Scope(str, Enum):
    READ = "read"
    CREATE = "create"
    DELETE = "delete"


class PermissionDenied(Exception):
    pass


@dataclass
class Token:
    """A purpose-generated token with an explicit scope set and an audience.

    The MCP spec requires the `aud` (audience) claim to match the receiving
    server, so a token minted for one server can't be replayed against another.
    We model that too.
    """
    name: str
    scopes: frozenset[Scope]
    audience: str

    def allows(self, scope: Scope) -> bool:
        return scope in self.scopes


@dataclass
class MockDatabaseService:
    """A pretend DB service. It checks the token's scope on every operation and
    validates the audience — exactly what a well-behaved MCP tool should do."""
    server_id: str
    databases: set[str] = field(default_factory=lambda: {"prod"})
    audit: list[str] = field(default_factory=list)

    def _authorize(self, token: Token, scope: Scope) -> None:
        if token.audience != self.server_id:
            raise PermissionDenied(
                f"audience mismatch: token for '{token.audience}', "
                f"server is '{self.server_id}'")
        if not token.allows(scope):
            raise PermissionDenied(
                f"token '{token.name}' lacks scope '{scope.value}'")

    def read(self, token: Token, db: str) -> dict:
        self._authorize(token, Scope.READ)
        self.audit.append(f"READ {db}")
        return {"db": db, "rows": 42}

    def create(self, token: Token, db: str) -> dict:
        self._authorize(token, Scope.CREATE)
        self.databases.add(db)
        self.audit.append(f"CREATE {db}")
        return {"db": db, "created": True}

    def delete(self, token: Token, db: str) -> dict:
        self._authorize(token, Scope.DELETE)
        self.databases.discard(db)
        self.audit.append(f"DELETE {db}")
        return {"db": db, "deleted": True}


def clone_workflow_with_hallucinated_cleanup(svc: MockDatabaseService,
                                             token: Token) -> dict:
    """Clone prod -> preprod, then a HALLUCINATED 'cleanup' step the model
    invented that tries to delete prod. Returns what happened under this token.
    """
    outcome = {"token": token.name, "steps": [], "prod_survived": True}

    # Legitimate steps the task actually needs.
    svc.read(token, "prod")
    outcome["steps"].append("read prod (ok)")
    svc.create(token, "preprod")
    outcome["steps"].append("create preprod (ok)")

    # The hallucinated step: "clean up the old prod copy". The model should
    # never do this, but agents are non-deterministic. The token is the guard.
    try:
        svc.delete(token, "prod")
        outcome["steps"].append("delete prod (EXECUTED!)")
    except PermissionDenied as e:
        outcome["steps"].append(f"delete prod (DENIED — {e})")

    outcome["prod_survived"] = "prod" in svc.databases
    return outcome


def _demo() -> None:
    server = "mcp://db-tools"

    scoped = Token("scoped-read-create", frozenset({Scope.READ, Scope.CREATE}),
                   audience=server)
    admin = Token("admin-all", frozenset({Scope.READ, Scope.CREATE, Scope.DELETE}),
                  audience=server)

    print("Scenario: agent clones prod -> preprod, then HALLUCINATES a "
          "'delete prod' cleanup step.\n")

    for token in (scoped, admin):
        svc = MockDatabaseService(server_id=server)  # fresh prod each run
        result = clone_workflow_with_hallucinated_cleanup(svc, token)
        print(f"[{token.name}]  scopes={sorted(s.value for s in token.scopes)}")
        for step in result["steps"]:
            print(f"    - {step}")
        verdict = "SAFE — prod still exists" if result["prod_survived"] \
            else "DISASTER — prod was deleted"
        print(f"    => {verdict}\n")

    # Audience check: a token minted for another server is rejected.
    foreign = Token("scoped-but-wrong-aud",
                    frozenset({Scope.READ, Scope.CREATE}),
                    audience="mcp://some-other-server")
    svc = MockDatabaseService(server_id=server)
    try:
        svc.read(foreign, "prod")
    except PermissionDenied as e:
        print(f"[aud check]  {e}  -> token replay across servers blocked")

    print("\nTakeaway: the scoped token makes the hallucinated DELETE fail "
          "safely. Reusing the user's admin credentials would have deleted "
          "prod. Token isolation limits the blast radius of a bad model step.")


if __name__ == "__main__":
    _demo()
