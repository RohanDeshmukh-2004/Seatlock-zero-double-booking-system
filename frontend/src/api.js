const API_BASE = (typeof window !== 'undefined' && window.location.port === '5173')
  ? 'http://localhost:8000'
  : '';

export function getAuthToken() {
  return localStorage.getItem('seatlock_token');
}

export function setAuthToken(token) {
  if (token) {
    localStorage.setItem('seatlock_token', token);
  } else {
    localStorage.removeItem('seatlock_token');
  }
}

export function getCurrentUser() {
  const user = localStorage.getItem('seatlock_user');
  return user ? JSON.parse(user) : null;
}

export function setCurrentUser(user) {
  if (user) {
    localStorage.setItem('seatlock_user', JSON.stringify(user));
  } else {
    localStorage.removeItem('seatlock_user');
  }
}

export async function apiRequest(endpoint, options = {}) {
  const token = getAuthToken();
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {})
  };

  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers
  });

  const data = await response.json().catch(() => ({}));

  if (!response.ok) {
    const errorMsg = data.detail || `Request failed with status ${response.status}`;
    const error = new Error(errorMsg);
    error.status = response.status;
    error.data = data;
    throw error;
  }

  return data;
}
