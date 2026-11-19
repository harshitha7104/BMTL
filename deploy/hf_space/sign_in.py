"""Small sign-in window: paste a Hugging Face access token, it is checked and saved in the Hugging Face cache on this PC.
The token never leaves this window except to huggingface.co; nothing is printed except the account name."""
from __future__ import annotations

import tkinter as tk


def main() -> None:
    root = tk.Tk()
    root.title("Hugging Face sign-in")
    root.attributes("-topmost", True)
    root.geometry("460x190")
    tk.Label(root, text="Paste your Hugging Face token below (Ctrl+V), then click Sign in.",
             wraplength=430, justify="left").pack(padx=14, pady=(14, 6), anchor="w")
    entry = tk.Entry(root, show="*", width=56)
    entry.pack(padx=14, pady=4)
    entry.focus_set()
    status = tk.Label(root, text="", wraplength=430, justify="left")
    status.pack(padx=14, pady=6, anchor="w")

    def sign_in() -> None:
        token = entry.get().strip()
        if not token.startswith("hf_"):
            status.config(text="That doesn't look like a token (it should start with hf_).", fg="red")
            return
        status.config(text="Checking...", fg="black")
        root.update()
        from huggingface_hub import HfApi, login

        try:
            info = HfApi(token=token).whoami()
        except Exception:
            status.config(text="Hugging Face did not accept that token. Copy it again and retry.", fg="red")
            return
        role = info.get("auth", {}).get("accessToken", {}).get("role", "")
        if role and role not in ("write", "fineGrained"):
            status.config(text="This token is read-only. Create a new one with 'Write' selected.", fg="red")
            return
        login(token=token, add_to_git_credential=False, skip_if_logged_in=False)
        print(f"signed in as {info['name']} (token type: {role or 'unknown'})")
        status.config(text=f"Signed in as {info['name']}. You can close this window.", fg="green")
        entry.delete(0, tk.END)
        root.after(2500, root.destroy)

    tk.Button(root, text="Sign in", command=sign_in, width=14).pack(pady=4)
    root.bind("<Return>", lambda _e: sign_in())
    root.mainloop()


if __name__ == "__main__":
    main()
