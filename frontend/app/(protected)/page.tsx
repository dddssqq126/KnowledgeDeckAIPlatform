import { redirect } from "next/navigation";

export default function ProtectedIndexRedirect() {
  redirect("/chat");
}
