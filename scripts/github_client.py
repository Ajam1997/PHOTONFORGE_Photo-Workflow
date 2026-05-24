"""GitHub REST and GraphQL API client for PHOTONForge scaffolding scripts."""
import os
import requests
from typing import Any


class GitHubClient:
    REST_BASE = "https://api.github.com"
    GRAPHQL_URL = "https://api.github.com/graphql"

    def __init__(self, token: str | None = None, owner: str = "Ajam1997", repo: str = "PHOTONFORGE_Photo-Workflow"):
        self.token = token or os.environ["GITHUB_TOKEN"]
        self.owner = owner
        self.repo = repo
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    # --- Labels ---

    def create_label(self, name: str, color: str, description: str) -> dict:
        """Create a label; return existing label if it already exists."""
        r = self._session.post(
            f"{self.REST_BASE}/repos/{self.owner}/{self.repo}/labels",
            json={"name": name, "color": color, "description": description},
        )
        if r.status_code == 422:
            # Already exists — fetch it
            r2 = self._session.get(
                f"{self.REST_BASE}/repos/{self.owner}/{self.repo}/labels/{requests.utils.quote(name, safe='')}",
            )
            r2.raise_for_status()
            return r2.json()
        r.raise_for_status()
        return r.json()

    # --- Issues ---

    def find_issue_by_title(self, search_term: str) -> dict | None:
        """Return first open Issue whose title contains search_term, or None."""
        r = self._session.get(
            f"{self.REST_BASE}/repos/{self.owner}/{self.repo}/issues",
            params={"state": "open", "per_page": 100},
        )
        r.raise_for_status()
        for issue in r.json():
            if search_term in issue.get("title", ""):
                return issue
        return None

    def create_issue(self, title: str, body: str, labels: list[str]) -> dict:
        """Create an Issue and return the response dict (includes number and node_id)."""
        r = self._session.post(
            f"{self.REST_BASE}/repos/{self.owner}/{self.repo}/issues",
            json={"title": title, "body": body, "labels": labels},
        )
        r.raise_for_status()
        return r.json()

    def get_or_create_issue(self, search_term: str, title: str, body: str, labels: list[str]) -> dict:
        """Return existing Issue matching search_term, or create it."""
        existing = self.find_issue_by_title(search_term)
        if existing:
            return existing
        return self.create_issue(title, body, labels)

    def add_sub_issue(self, parent_number: int, child_issue_id: int) -> None:
        """Add child_issue_id as a sub-issue of parent_number."""
        r = self._session.post(
            f"{self.REST_BASE}/repos/{self.owner}/{self.repo}/issues/{parent_number}/sub_issues",
            json={"sub_issue_id": child_issue_id},
        )
        r.raise_for_status()

    def post_comment(self, issue_number: int, body: str) -> dict:
        r = self._session.post(
            f"{self.REST_BASE}/repos/{self.owner}/{self.repo}/issues/{issue_number}/comments",
            json={"body": body},
        )
        r.raise_for_status()
        return r.json()

    def set_labels(self, issue_number: int, labels: list[str]) -> None:
        r = self._session.post(
            f"{self.REST_BASE}/repos/{self.owner}/{self.repo}/issues/{issue_number}/labels",
            json={"labels": labels},
        )
        r.raise_for_status()

    def close_issue(self, issue_number: int) -> None:
        r = self._session.patch(
            f"{self.REST_BASE}/repos/{self.owner}/{self.repo}/issues/{issue_number}",
            json={"state": "closed"},
        )
        r.raise_for_status()

    def list_issues(self, labels: str | None = None, state: str = "open") -> list[dict]:
        params: dict[str, Any] = {"state": state, "per_page": 100}
        if labels:
            params["labels"] = labels
        issues = []
        page = 1
        while True:
            params["page"] = page
            r = self._session.get(
                f"{self.REST_BASE}/repos/{self.owner}/{self.repo}/issues",
                params=params,
            )
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            issues.extend(batch)
            page += 1
        return issues

    # --- GraphQL (Projects v2) ---

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        r = self._session.post(
            self.GRAPHQL_URL,
            json={"query": query, "variables": variables or {}},
        )
        r.raise_for_status()
        data = r.json()
        if "errors" in data:
            raise RuntimeError(f"GraphQL error: {data['errors']}")
        return data["data"]

    def get_owner_node_id(self) -> str:
        data = self.graphql(
            "query($login: String!) { user(login: $login) { id } }",
            {"login": self.owner},
        )
        return data["user"]["id"]

    def create_project(self, owner_id: str, title: str) -> dict:
        """Create a Projects v2 board. Returns {"id": ..., "number": ...}."""
        data = self.graphql(
            """
            mutation($ownerId: ID!, $title: String!) {
              createProjectV2(input: {ownerId: $ownerId, title: $title}) {
                projectV2 { id number }
              }
            }
            """,
            {"ownerId": owner_id, "title": title},
        )
        return data["createProjectV2"]["projectV2"]

    def add_project_item(self, project_id: str, issue_node_id: str) -> str:
        """Add an Issue to a Projects v2 board. Returns the item node ID."""
        data = self.graphql(
            """
            mutation($projectId: ID!, $contentId: ID!) {
              addProjectV2Item(input: {projectId: $projectId, contentId: $contentId}) {
                item { id }
              }
            }
            """,
            {"projectId": project_id, "contentId": issue_node_id},
        )
        return data["addProjectV2Item"]["item"]["id"]

    def create_project_field(self, project_id: str, name: str, data_type: str, options: list[str] | None = None) -> str:
        """Create a custom field on a Projects v2 board. Returns field node ID.
        data_type: TEXT | SINGLE_SELECT | NUMBER | DATE
        options: required when data_type is SINGLE_SELECT
        """
        if data_type == "SINGLE_SELECT":
            opts = [{"name": o} for o in (options or [])]
            data = self.graphql(
                """
                mutation($projectId: ID!, $name: String!, $options: [ProjectV2SingleSelectFieldOptionInput!]!) {
                  createProjectV2Field(input: {projectId: $projectId, name: $name, dataType: SINGLE_SELECT, singleSelectOptions: $options}) {
                    projectV2Field { ... on ProjectV2SingleSelectField { id } }
                  }
                }
                """,
                {"projectId": project_id, "name": name, "options": opts},
            )
            return data["createProjectV2Field"]["projectV2Field"]["id"]
        else:
            data = self.graphql(
                f"""
                mutation($projectId: ID!, $name: String!) {{
                  createProjectV2Field(input: {{projectId: $projectId, name: $name, dataType: {data_type}}}) {{
                    projectV2Field {{ ... on ProjectV2Field {{ id }} }}
                  }}
                }}
                """,
                {"projectId": project_id, "name": name},
            )
            return data["createProjectV2Field"]["projectV2Field"]["id"]

    def update_project_text_field(self, project_id: str, item_id: str, field_id: str, value: str) -> None:
        self.graphql(
            """
            mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $value: String!) {
              updateProjectV2ItemFieldValue(input: {
                projectId: $projectId, itemId: $itemId, fieldId: $fieldId,
                value: {text: $value}
              }) { projectV2Item { id } }
            }
            """,
            {"projectId": project_id, "itemId": item_id, "fieldId": field_id, "value": value},
        )

    def update_project_select_field(self, project_id: str, item_id: str, field_id: str, option_id: str) -> None:
        self.graphql(
            """
            mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
              updateProjectV2ItemFieldValue(input: {
                projectId: $projectId, itemId: $itemId, fieldId: $fieldId,
                value: {singleSelectOptionId: $optionId}
              }) { projectV2Item { id } }
            }
            """,
            {"projectId": project_id, "itemId": item_id, "fieldId": field_id, "optionId": option_id},
        )
