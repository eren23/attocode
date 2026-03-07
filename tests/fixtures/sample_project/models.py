"""Data models for the sample project."""

from dataclasses import dataclass, field


@dataclass
class User:
    """Represents an application user."""

    name: str
    email: str
    active: bool = True

    def deactivate(self) -> None:
        self.active = False


@dataclass
class Config:
    """Application configuration."""

    path: str
    debug: bool = False
    max_retries: int = 3
    tags: list[str] = field(default_factory=list)
