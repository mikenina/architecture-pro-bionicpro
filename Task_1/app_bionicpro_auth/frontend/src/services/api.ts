const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

/**
 * Универсальная функция для API-запросов
 */
export async function apiCall(url: string, options: RequestInit = {}) {
    const fullUrl = `${API_URL}${url}`;

    const response = await fetch(fullUrl, {
        ...options,
        credentials: 'include',
        headers: {
            'Content-Type': 'application/json',
            ...options.headers,
        },
    });

    // Проверяем, нужно ли обновить session cookie (ротация сессии)
    const newSessionId = response.headers.get('X-New-Session-Id');
    if (newSessionId) {
        await fetch(`${API_URL}/auth/refresh-cookie`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: newSessionId }),
            credentials: 'include',
        });
    }

    return response;
}

/**
 * GET запрос
 */
export async function apiGet<T = any>(url: string): Promise<T> {
    const response = await apiCall(url, { method: 'GET' });

    if (!response.ok) {
        if (response.status === 401) {
            throw new Error('Unauthorized');
        }
        throw new Error(`API Error: ${response.status}`);
    }

    if (response.status === 204) {
        return {} as T;
    }

    return response.json();
}

/**
 * POST запрос
 */
export async function apiPost<T = any>(url: string, data?: any): Promise<T> {
    const response = await apiCall(url, {
        method: 'POST',
        body: data ? JSON.stringify(data) : undefined,
    });

    if (!response.ok) {
        if (response.status === 401) {
            throw new Error('Unauthorized');
        }
        throw new Error(`API Error: ${response.status}`);
    }

    if (response.status === 204) {
        return {} as T;
    }

    return response.json();
}

/**
 * DELETE запрос
 */
export async function apiDelete<T = any>(url: string): Promise<T> {
    const response = await apiCall(url, { method: 'DELETE' });

    if (!response.ok) {
        if (response.status === 401) {
            throw new Error('Unauthorized');
        }
        throw new Error(`API Error: ${response.status}`);
    }

    if (response.status === 204) {
        return {} as T;
    }

    return response.json();
}