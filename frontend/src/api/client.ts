/**
 * PayLap API Client for /v1 endpoints.
 */

export interface ApiError {
  type: string;
  code: string;
  message: string;
  request_id?: string;
  details?: any;
}

export class PayLapClient {
  private static getHeaders(idempotencyKey?: string): HeadersInit {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };

    const apiKey = localStorage.getItem("paylap_api_key");
    if (apiKey) {
      headers["Authorization"] = `Bearer ${apiKey.trim()}`;
    }

    if (idempotencyKey) {
      headers["Idempotency-Key"] = idempotencyKey;
    }

    const csrfToken = localStorage.getItem("paylap_csrf_token");
    if (csrfToken) {
      headers["X-CSRF-Token"] = csrfToken;
    }

    return headers;
  }

  private static async handleResponse<T>(res: Response): Promise<T> {
    if (!res.ok) {
      let errBody: any;
      try {
        errBody = await res.json();
      } catch {
        errBody = { error: { message: res.statusText, code: String(res.status) } };
      }
      const err = errBody.error || { message: errBody.detail || "Request failed", code: String(res.status) };
      throw err;
    }

    if (res.status === 204) {
      return {} as T;
    }
    return res.json();
  }

  static async get<T>(path: string): Promise<T> {
    const res = await fetch(path, {
      method: "GET",
      headers: this.getHeaders(),
      credentials: "include",
    });
    return this.handleResponse<T>(res);
  }

  static async post<T>(path: string, body?: any, idempotencyKey?: string): Promise<T> {
    const res = await fetch(path, {
      method: "POST",
      headers: this.getHeaders(idempotencyKey),
      body: body ? JSON.stringify(body) : undefined,
      credentials: "include",
    });
    return this.handleResponse<T>(res);
  }

  static async put<T>(path: string, body?: any): Promise<T> {
    const res = await fetch(path, {
      method: "PUT",
      headers: this.getHeaders(),
      body: body ? JSON.stringify(body) : undefined,
      credentials: "include",
    });
    return this.handleResponse<T>(res);
  }

  static async delete<T>(path: string): Promise<T> {
    const res = await fetch(path, {
      method: "DELETE",
      headers: this.getHeaders(),
      credentials: "include",
    });
    return this.handleResponse<T>(res);
  }
}
