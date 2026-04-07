import React, { useState } from 'react';
import { getReport } from '../services/api';

interface ReportData {
    user_id: string;
    user_email: string;
    start_date: string;
    end_date: string;
    generated_at: string;
    data_updated_at: string;
    total_intervals: number;
    data: Array<{
        interval_start: string;
        prosthesis_type: string;
        avg_frequency: number;
        avg_duration: number;
        avg_amplitude: number;
        signal_count: number;
    }>;
}

interface ReportResponse {
    cached: boolean;
    valid: boolean;
    cdn_url: string;
    data_updated_at: string;
    report_data: ReportData | null;
}

const ReportPage: React.FC = () => {
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [reportResponse, setReportResponse] = useState<ReportResponse | null>(null);
    const [reportData, setReportData] = useState<ReportData | null>(null);

    const [startDate, setStartDate] = useState(() => {
        const date = new Date();
        date.setDate(date.getDate() - 7);
        return date.toISOString().slice(0, 10);
    });
    const [endDate, setEndDate] = useState(() => {
        return new Date().toISOString().slice(0, 10);
    });

    const formatDateTime = (isoString: string) => {
        if (!isoString) return '—';
        try {
            const date = new Date(isoString);
            return date.toLocaleString('ru-RU', {
                day: '2-digit',
                month: '2-digit',
                year: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            });
        } catch {
            return isoString;
        }
    };

    const formatDateForDisplay = (dateStr: string) => {
        if (!dateStr) return '—';
        const parts = dateStr.split('-');
        if (parts.length === 3) {
            return `${parts[2]}.${parts[1]}.${parts[0]}`;
        }
        return dateStr;
    };

    const downloadReport = async () => {
        if (!startDate || !endDate) {
            setError('Please select start and end dates');
            return;
        }

        // Преобразуем даты в формат с временем (начало и конец дня)
        const startDateTime = `${startDate} 00:00:00`;
        const endDateTime = `${endDate} 23:59:59`;

        try {
            setLoading(true);
            setError(null);
            setReportResponse(null);
            setReportData(null);

            const response = await getReport(startDateTime, endDateTime);
            setReportResponse(response);

            if (response.report_data) {
                setReportData(response.report_data);
            } else if (response.cdn_url) {
                try {
                    const cdnResponse = await fetch(response.cdn_url);
                    const cdnData = await cdnResponse.json();
                    setReportData(cdnData);
                } catch (cdnErr) {
                    console.error('Failed to load report from CDN:', cdnErr);
                }
            }
        } catch (err) {
            setError(err instanceof Error ? err.message : 'An error occurred');
        } finally {
            setLoading(false);
        }
    };

    const downloadAsJSON = () => {
        if (!reportData) return;

        const dataStr = JSON.stringify(reportData, null, 2);
        const blob = new Blob([dataStr], { type: 'application/json' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `report_${reportData.user_id}_${reportData.start_date.split(' ')[0]}_to_${reportData.end_date.split(' ')[0]}.json`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
    };

    return (
        <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100 p-4">
            <div className="p-8 bg-white rounded-lg shadow-md w-full max-w-5xl">
                <h1 className="text-2xl font-bold mb-6">Usage Reports</h1>

                <div className="flex flex-col sm:flex-row gap-4 mb-6">
                    <div className="flex-1">
                        <label className="block text-sm font-medium text-gray-700 mb-1">Start Date</label>
                        <input
                            type="date"
                            value={startDate}
                            onChange={(e) => setStartDate(e.target.value)}
                            className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                    </div>
                    <div className="flex-1">
                        <label className="block text-sm font-medium text-gray-700 mb-1">End Date</label>
                        <input
                            type="date"
                            value={endDate}
                            onChange={(e) => setEndDate(e.target.value)}
                            className="w-full px-3 py-2 border rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                    </div>
                    <div className="flex items-end">
                        <button
                            onClick={downloadReport}
                            disabled={loading}
                            className={`px-6 py-2 bg-blue-500 text-white rounded-lg hover:bg-blue-600 ${
                                loading ? 'opacity-50 cursor-not-allowed' : ''
                            }`}
                        >
                            {loading ? 'Loading...' : 'Get Report'}
                        </button>
                    </div>
                </div>

                {error && (
                    <div className="mb-4 p-4 bg-red-100 text-red-700 rounded">
                        {error}
                    </div>
                )}

                {/* Report results */}
                {reportData && (
                    <div className="mt-6">
                        <div className="flex justify-between items-center mb-4">
                            <h2 className="text-xl font-semibold">Report Results</h2>
                            <button
                                onClick={downloadAsJSON}
                                className="px-4 py-2 bg-green-500 text-white rounded hover:bg-green-600"
                            >
                                Download JSON
                            </button>
                        </div>

                        {/* Metadata block with timestamps */}
                        <div className="bg-gray-50 p-4 rounded-lg mb-4 text-sm">
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                                <div>
                                    <span className="font-semibold">Data last updated:</span>
                                    <span className="ml-2 text-gray-600">{formatDateTime(reportData.data_updated_at)}</span>
                                </div>
                                <div>
                                    <span className="font-semibold">Report generated:</span>
                                    <span className="ml-2 text-gray-600">{formatDateTime(reportData.generated_at)}</span>
                                </div>
                                <div>
                                    <span className="font-semibold">User ID:</span>
                                    <span className="ml-2 text-gray-600">{reportData.user_id}</span>
                                </div>
                                <div>
                                    <span className="font-semibold">Period:</span>
                                    <span className="ml-2 text-gray-600">
                                        {formatDateForDisplay(reportData.start_date.split(' ')[0])} — {formatDateForDisplay(reportData.end_date.split(' ')[0])}
                                    </span>
                                </div>
                                <div>
                                    <span className="font-semibold">Total intervals:</span>
                                    <span className="ml-2 text-gray-600">{reportData.total_intervals}</span>
                                </div>
                                <div>
                                    <span className="font-semibold">Cache status:</span>
                                    <span className={`ml-2 ${reportResponse?.cached ? 'text-green-600' : 'text-yellow-600'}`}>
                                        {reportResponse?.cached ? 'Cached' : 'Freshly generated'}
                                    </span>
                                </div>
                            </div>
                        </div>

                        {/* Data table */}
                        {reportData.total_intervals > 0 ? (
                            <div className="overflow-x-auto">
                                <table className="min-w-full border border-gray-200">
                                    <thead className="bg-gray-50">
                                    <tr>
                                        <th className="px-4 py-2 border text-left">Time Interval</th>
                                        <th className="px-4 py-2 border text-left">Prosthesis Type</th>
                                        <th className="px-4 py-2 border text-right">Avg Frequency (Hz)</th>
                                        <th className="px-4 py-2 border text-right">Avg Duration (ms)</th>
                                        <th className="px-4 py-2 border text-right">Avg Amplitude</th>
                                        <th className="px-4 py-2 border text-right">Signal Count</th>
                                    </tr>
                                    </thead>
                                    <tbody>
                                    {reportData.data.map((row, idx) => (
                                        <tr key={idx} className="hover:bg-gray-50">
                                            <td className="px-4 py-2 border">{row.interval_start}</td>
                                            <td className="px-4 py-2 border">{row.prosthesis_type}</td>
                                            <td className="px-4 py-2 border text-right">{row.avg_frequency}</td>
                                            <td className="px-4 py-2 border text-right">{row.avg_duration}</td>
                                            <td className="px-4 py-2 border text-right">{row.avg_amplitude}</td>
                                            <td className="px-4 py-2 border text-right">{row.signal_count}</td>
                                        </tr>
                                    ))}
                                    </tbody>
                                </table>
                            </div>
                        ) : (
                            <div className="text-center py-8 text-gray-500">
                                No data found for the selected period
                            </div>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
};

export default ReportPage;