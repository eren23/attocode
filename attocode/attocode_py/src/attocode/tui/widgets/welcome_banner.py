"""Welcome banner widget shown at startup."""

from __future__ import annotations

from textual.widgets import Static

from attocode.tui.widgets.mascot import render_startup_banner


class WelcomeBanner(Static):
    """Displays the branded startup banner with ghost mascot and figlet text.

    Hidden once the user submits their first prompt.
    """

    DEFAULT_CSS = """
    WelcomeBanner {
        height: auto;
        padding: 1 2;
        content-align: center middle;
    }
    """

    def __init__(
        self,
        model: str = "",
        git_branch: str = "",
        version: str = "",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._model = model
        self._git_branch = git_branch
        self._version = version

    def on_mount(self) -> None:
        banner = render_startup_banner(
            model=self._model,
            git_branch=self._git_branch,
            version=self._version,
        )
        self.update(banner)
