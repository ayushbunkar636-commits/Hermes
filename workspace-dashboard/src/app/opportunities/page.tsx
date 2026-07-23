'use client';
import { useEffect, useState } from 'react';
import { Search, Filter, Download } from 'lucide-react';

export default function OpportunitiesPage() {
  const [data, setData] = useState<any[]>([]);
  const [statusFilter, setStatusFilter] = useState('pending');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetch(`/api/opportunities?status=${statusFilter}&limit=20`)
      .then(res => res.json())
      .then(d => {
        setData(d.data || []);
        setLoading(false);
      });
  }, [statusFilter]);

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center mb-8">
        <h1 className="text-3xl font-bold text-white">Opportunities Database</h1>
        <div className="flex gap-4">
          <select 
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="bg-gray-800 text-white border border-gray-700 rounded-lg px-4 py-2"
          >
            <option value="pending">Pending</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
            <option value="archived">Archived</option>
          </select>
          <button className="flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg transition-colors">
            <Download size={18} /> Export CSV
          </button>
        </div>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-2xl overflow-hidden shadow-sm">
        <div className="p-4 border-b border-gray-800 flex items-center gap-4">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
            <input 
              type="text" 
              placeholder="Search opportunities..." 
              className="w-full bg-gray-950 border border-gray-800 text-white pl-10 pr-4 py-2 rounded-lg focus:outline-none focus:border-blue-500"
            />
          </div>
          <button className="flex items-center gap-2 text-gray-400 hover:text-white px-4 py-2 bg-gray-800 rounded-lg">
            <Filter size={18} /> Filter
          </button>
        </div>
        
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm text-gray-400">
            <thead className="bg-gray-950/50 text-gray-300 uppercase font-medium">
              <tr>
                <th className="px-6 py-4">Title / URL</th>
                <th className="px-6 py-4">Platform</th>
                <th className="px-6 py-4 text-center">Score</th>
                <th className="px-6 py-4 text-center">Confidence</th>
                <th className="px-6 py-4 text-center">Impact</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr><td colSpan={5} className="text-center py-8">Loading...</td></tr>
              ) : data.length === 0 ? (
                <tr><td colSpan={5} className="text-center py-8">No opportunities found.</td></tr>
              ) : (
                data.map((opp) => (
                  <tr key={opp.id} className="border-b border-gray-800 hover:bg-gray-800/50 transition-colors">
                    <td className="px-6 py-4 max-w-xs">
                      <div className="font-medium text-white truncate">{opp.title || 'Unknown Title'}</div>
                      <a href={opp.url} target="_blank" rel="noreferrer" className="text-xs text-blue-400 hover:underline truncate block mt-1">{opp.url}</a>
                    </td>
                    <td className="px-6 py-4">
                      <span className="bg-gray-800 px-2.5 py-1 rounded-md text-xs">{opp.platform || 'Web'}</span>
                    </td>
                    <td className="px-6 py-4 text-center">
                      <span className="font-bold text-white">{opp.score_100 || '-'}</span>
                    </td>
                    <td className="px-6 py-4 text-center">
                      {opp.confidence ? `${opp.confidence}%` : '-'}
                    </td>
                    <td className="px-6 py-4 text-center">
                      {opp.business_impact ? (
                        <span className="bg-purple-900/30 text-purple-400 border border-purple-800/50 px-2 py-1 rounded text-xs">
                          {opp.business_impact}
                        </span>
                      ) : '-'}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
