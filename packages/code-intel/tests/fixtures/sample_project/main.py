"""Sample application entry point for integration tests."""

from utils import parse_config, validate_input
from models import User, Config


class App:
    """Main application class."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.users: list[User] = []

    def add_user(self, name: str, email: str) -> User:
        """Create and register a new user."""
        validate_input(name)
        user = User(name=name, email=email)
        self.users.append(user)
        return user

    def run(self) -> None:
        """Start the application."""
        settings = parse_config(self.config.path)
        print(f"Running with {len(settings)} settings")


def main() -> None:
    config = Config(path="config.yaml", debug=True)
    app = App(config)
    app.run()


if __name__ == "__main__":
    main()
