import React, { useState } from 'react';

const API_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

const LoginPage: React.FC = () => {
    const [error, setError] = useState<string | null>(null);

    const startLogin = () => {
        setError(null);
        window.location.href = `${API_URL}/auth/login`;
    };

    return (
        <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
            <div className="p-8 bg-white rounded-lg shadow-md w-96">
                <div className="text-center mb-6">
                    <h1 className="text-2xl font-bold text-gray-800">BionicPRO Reports</h1>
                    <p className="text-gray-500 mt-2">Sign in to access your reports</p>
                </div>

                {error && (
                    <div className="mb-4 p-3 bg-red-100 border border-red-400 text-red-700 rounded-lg">
                        <div className="font-semibold">Authentication Error</div>
                        <div className="text-sm mt-1">{error}</div>
                    </div>
                )}

                <button
                    onClick={startLogin}
                    className="w-full bg-blue-500 text-white py-2 px-4 rounded-lg hover:bg-blue-600 transition-colors font-medium"
                >
                    Login with BionicPRO
                </button>

                <p className="text-xs text-gray-400 text-center mt-4">
                    You will be redirected to the secure authentication service
                </p>
            </div>
        </div>
    );
};

export default LoginPage;