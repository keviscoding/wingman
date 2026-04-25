import { useRouter } from "expo-router";
import { useState } from "react";
import { AuthForm } from "../../components/AuthForm";
import { useAuth } from "../../lib/auth";

export default function LoginScreen() {
  const { signIn } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async () => {
    if (!email.trim() || !password) {
      setError("Email and password are required.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await signIn(email.trim(), password);
      router.replace("/");
    } catch (e: any) {
      setError(prettyError(e?.detail || e?.message || "Login failed"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthForm
      mode="login"
      email={email}
      setEmail={setEmail}
      password={password}
      setPassword={setPassword}
      loading={loading}
      error={error}
      onSubmit={onSubmit}
    />
  );
}

function prettyError(detail: string): string {
  switch (detail) {
    case "invalid_credentials":
      return "Wrong email or password.";
    case "email_already_registered":
      return "That email already has an account. Try logging in.";
    case "user_not_found":
      return "Account not found.";
    default:
      if (detail.startsWith("network:")) return "Can't reach the server. Check your connection.";
      return detail;
  }
}
