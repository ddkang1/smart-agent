"""Helper functions for setting up the Chainlit environment."""

import pathlib

def create_translation_files():
    """Create translation directory and files if they don't exist.
    
    This function ensures that the necessary Chainlit configuration files
    are present in the .chainlit directory.
    """
    # Create .chainlit directory in the current working directory
    chainlit_dir = pathlib.Path.cwd() / ".chainlit"
    translations_dir = chainlit_dir / "translations"

    # Create directories if they don't exist
    translations_dir.mkdir(parents=True, exist_ok=True)

    # Create en.json translation file
    en_file = translations_dir / "en.json"
    if not en_file.exists():
        # Copy content from en-US.json if it exists, otherwise create a minimal file
        en_us_file = translations_dir / "en-US.json"
        if en_us_file.exists():
            en_file.write_text(en_us_file.read_text())
        else:
            # Create a minimal translation file
            en_file.write_text('{}')

    # Create chainlit.md file if it doesn't exist
    chainlit_md = chainlit_dir / "chainlit.md"
    if not chainlit_md.exists():
        chainlit_md.write_text("# Welcome to Smart Agent\n\nThis is a Chainlit UI for Smart Agent.")
