import { useRouter } from "expo-router";
import { useState } from "react";
import { AuthForm } from "../../components/AuthForm";
import { useAuth } from "../../lib/auth";

export default function SignupScreen() {
  const { signUp } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async () => {
    if (!email.trim() || password.length < 8) {
      setError(
        password.length < 8
          ? "Password must be at least 8 characters."
          : "Email is required.",
      );
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await signUp(email.trim(), password, name.trim() || undefined);
      router.replace("/");
    } catch (e: any) {
      setError(prettyError(e?.detail || e?.message || "Sign up failed"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthForm
      mode="signup"
      email={email}
      setEmail={setEmail}
      password={password}
      setPassword={setPassword}
      name={name}
      setName={setName}
      loading={loading}
      error={error}
      onSubmit={onSubmit}
    />
  );
}

function prettyError(detail: string): string {
  if (detail === "email_already_registered") return "That email is already registered.";
  if (detail.startsWith("network:")) return "Can't reach the server. Check your connection.";
  return detail;
}
