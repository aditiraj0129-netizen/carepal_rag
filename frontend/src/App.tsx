import { useEffect, useState } from "react";
import { AdminPage } from "./components/AdminPage";
import { ChatPage } from "./components/ChatPage";

const route = () => (window.location.hash.startsWith("#/admin") ? "admin" : "chat");

export default function App() {
  const [view, setView] = useState(route);
  useEffect(() => {
    const on = () => setView(route());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return view === "admin" ? <AdminPage /> : <ChatPage />;
}
