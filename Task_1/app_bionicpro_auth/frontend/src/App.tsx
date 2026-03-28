import React, { useState, useEffect } from 'react';
import ReportPage from './components/ReportPage';
import LoginPage from './components/LoginPage';
import { apiGet, apiPost } from './services/api';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

const App: React.FC = () => {
    const [isAuthenticated, setIsAuthenticated] = useState<boolean | null>(null);
    const [user, setUser] = useState<any>(null);
    const [loading, setLoading] = useState(true);
    const [processingCallback, setProcessingCallback] = useState(false);

    useEffect(() => {
        // Проверяем, есть ли code в URL (callback от Keycloak)
        const params = new URLSearchParams(window.location.search);
        const code = params.get('code');
        const error = params.get('error');

        if (error) {
            // Ошибка аутентификации
            window.history.replaceState({}, '', '/');
            setIsAuthenticated(false);
            setLoading(false);
            return;
        }

        if (code && !processingCallback) {
            // Обрабатываем callback
            setProcessingCallback(true);
            handleCallback(code);
            return;
        }

        // Нормальная проверка аутентификации
        checkAuth();
    }, []);

    const handleCallback = async (code: string) => {
        try {
            // Отправляем code в auth-service
            const response = await fetch(`${API_URL}/auth/callback?code=${encodeURIComponent(code)}`, {
                method: 'GET',
                credentials: 'include'
            });

            const data = await response.json();

            if (data.success) {
                // Cookie установлена, очищаем URL и проверяем аутентификацию
                window.history.replaceState({}, '', '/');
                await checkAuth();
            } else {
                setIsAuthenticated(false);
                setLoading(false);
                window.history.replaceState({}, '', '/');
            }
        } catch (err) {
            console.error('Callback error:', err);
            setIsAuthenticated(false);
            setLoading(false);
            window.history.replaceState({}, '', '/');
        } finally {
            setProcessingCallback(false);
        }
    };

    const checkAuth = async () => {
        setLoading(true);
        try {
            const userData = await apiGet('/auth/me');
            setUser(userData);
            setIsAuthenticated(true);
        } catch (err) {
            setIsAuthenticated(false);
        } finally {
            setLoading(false);
        }
    };

    const handleLogout = async () => {
        try {
            await apiPost('/auth/logout');
            setIsAuthenticated(false);
            setUser(null);
        } catch (err) {
            console.error('Logout failed:', err);
        }
    };

    // Показываем загрузку при обработке callback
    if (processingCallback) {
        return (
            <div className="flex items-center justify-center min-h-screen bg-gray-100">
                <div className="text-center">
                    <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500 mx-auto"></div>
                    <p className="mt-4 text-gray-600">Processing login...</p>
                </div>
            </div>
        );
    }

    if (loading) {
        return (
            <div className="flex items-center justify-center min-h-screen bg-gray-100">
                <div className="text-center">
                    <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500 mx-auto"></div>
                    <p className="mt-4 text-gray-600">Loading...</p>
                </div>
            </div>
        );
    }

    if (!isAuthenticated) {
        return <LoginPage />;
    }

    return (
        <div className="App">
            <div className="flex justify-between items-center p-4 bg-white shadow-md">
                <h1 className="text-xl font-bold text-gray-800">BionicPRO Reports</h1>
                <div className="flex items-center space-x-4">
          <span className="text-gray-600">
            Welcome, <span className="font-semibold">{user?.username || user?.email}</span>
          </span>
                    <button
                        onClick={handleLogout}
                        className="px-3 py-1 bg-red-500 text-white rounded hover:bg-red-600 transition-colors"
                    >
                        Logout
                    </button>
                </div>
            </div>
            <ReportPage />
        </div>
    );
};

export default App;