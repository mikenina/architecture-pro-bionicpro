const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';
const REPORT_API_URL = process.env.REACT_APP_REPORT_API_URL || 'http://localhost:8001';

async function handleSessionRotation(response: Response): Promise<void> {
    // HTTP заголовки регистронезависимы, но для надёжности ищем оба варианта
    const newSessionId = response.headers.get('x-new-session-id') ||
        response.headers.get('X-New-Session-Id');

    console.log('Checking for new session id:', newSessionId);

    if (newSessionId) {
        console.log('Refreshing cookie with new session id:', newSessionId);
        await fetch(`${API_URL}/auth/refresh-cookie`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: newSessionId }),
            credentials: 'include',
        });
    }
}

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

    await handleSessionRotation(response);
    return response;
}

export async function reportApiCall(url: string, options: RequestInit = {}) {
    const fullUrl = `${REPORT_API_URL}${url}`;

    console.log('reportApiCall to:', fullUrl);

    const response = await fetch(fullUrl, {
        ...options,
        credentials: 'include',
        headers: {
            'Content-Type': 'application/json',
            ...options.headers,
        },
    });

    // Временное логирование для отладки
    console.log('X-New-Session-Id header:', response.headers.get('x-new-session-id'));
    console.log('X-New-Session-Id header (case-sensitive):', response.headers.get('X-New-Session-Id'));
    console.log('All headers as string:', response.headers);

    await handleSessionRotation(response);
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

export async function getReport(startDate: string, endDate: string) {
    const params = new URLSearchParams({
        start_date: startDate,
        end_date: endDate
    });

    const response = await reportApiCall(`/reports?${params.toString()}`, {
        method: 'GET'
    });

    if (!response.ok) {
        throw new Error(`Report API Error: ${response.status}`);
    }

    return response.json();
}