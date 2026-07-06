import type { ReactNode } from "react";
import { useAuth } from "@clerk/clerk-react";
import { Navigate } from "react-router-dom";

interface Props {
  children: ReactNode;
}

/**
 * Redirects signed-out visitors to the landing page. This is a UX
 * convenience, NOT the actual security boundary -- every API call the
 * dashboard makes is independently verified server-side (see
 * backend/app/auth.py). Someone could delete this component entirely and
 * the API would still reject unauthenticated requests; the reverse isn't
 * true, which is why the backend check is what actually protects the Qwen
 * credit budget.
 */
export default function ProtectedRoute({ children }: Props) {
  const { isLoaded, isSignedIn } = useAuth();

  if (!isLoaded) {
    return null;
  }

  if (!isSignedIn) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}
