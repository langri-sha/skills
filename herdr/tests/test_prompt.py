import unittest

from support import herdr


class PromptHasText(unittest.TestCase):
    def test_a_bare_prompt_has_no_text(self):
        for screen in (
            "user@host:~/repo$ \n",
            "~/repo main ❯ \n",
            "[10:20] root# \n",
            "~/repo > main % \n",
            "(venv) $\n",
        ):
            with self.subTest(screen=screen):
                self.assertFalse(herdr.prompt_has_text(screen))

    def test_text_after_the_last_prompt_end_is_typed_input(self):
        for screen in (
            "user@host:~/repo$ git sta\n",
            "~/repo main ❯ ls -l\n",
            "output\nroot# vim notes.md\n",
        ):
            with self.subTest(screen=screen):
                self.assertTrue(herdr.prompt_has_text(screen))

    def test_a_dollar_inside_a_word_is_not_a_prompt_end(self):
        self.assertFalse(herdr.prompt_has_text("price is $5 today\n"))

    def test_an_empty_screen_has_no_text(self):
        self.assertFalse(herdr.prompt_has_text(""))


RULE = "─" * 20


class AgentInputText(unittest.TestCase):
    def test_an_empty_box_has_no_text(self):
        self.assertFalse(herdr.agent_input_text(f"{RULE}\n❯\xa0\n{RULE}\n  Opus\n"))

    def test_text_on_the_prompt_line_is_typed_input(self):
        self.assertTrue(herdr.agent_input_text(f"{RULE}\n❯ fix it\n{RULE}\n"))

    def test_a_suggestion_is_not_typed_input(self):
        self.assertFalse(
            herdr.agent_input_text(f'{RULE}\n❯ Try "fix lint errors"\n{RULE}\n')
        )

    def test_a_second_line_after_shift_enter_is_typed_input(self):
        self.assertTrue(
            herdr.agent_input_text(f"{RULE}\n❯\xa0\n  second line\n{RULE}\n")
        )

    def test_a_second_line_after_a_suggestion_is_typed_input(self):
        text = f'{RULE}\n❯ Try "fix lint errors"\n  and more\n{RULE}\n'
        self.assertTrue(herdr.agent_input_text(text))

    def test_the_footer_below_the_closing_rule_is_not_input(self):
        text = f"{RULE}\n❯\xa0\n{RULE}\n  Opus 5.5 · high\n  ⏵⏵ bypass permissions on\n"
        self.assertFalse(herdr.agent_input_text(text))

    def test_a_box_cut_off_before_its_closing_rule_is_not_guessed_at(self):
        self.assertFalse(herdr.agent_input_text("❯\xa0\n  Opus 5.5 · high\n"))


if __name__ == "__main__":
    unittest.main()
