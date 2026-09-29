const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export async function api(path, options = {}) {
  const token = localStorage.getItem("lukes_command_center_token");
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(`${API_URL}${path}`, { ...options, headers });
  const data = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    const message = Array.isArray(detail)
      ? detail.map((item) => item.msg).join("; ")
      : detail || "Something went wrong";
    const error = new Error(message);
    error.status = response.status;
    throw error;
  }
  return data;
}
