'use client';
import { useEffect, useState } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import { TrendingUp, Activity, CheckCircle, Clock } from 'lucide-react';

export default function Overview() {
  const [data, setData] = useState<any>(null);

  useEffect(() => {
    fetch('/api/overview')
      .then(res => res.json())
      .then(d => setData(d));
  }, []);

  if (!data) return <div className="text-white">Loading Overview...</div>;

  const chartData = data.chartData || [
    { name: 'Mon', opps: 0 },
    { name: 'Tue', opps: 0 },
    { name: 'Wed', opps: 0 },
    { name: 'Thu', opps: 0 },
    { name: 'Fri', opps: 0 },
    { name: 'Sat', opps: 0 },
    { name: 'Sun', opps: 0 },
  ];

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold text-white mb-8">Analytics Overview</h1>
      
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <div className="bg-gray-900 border border-gray-800 p-6 rounded-2xl shadow-sm">
          <div className="flex justify-between items-start">
            <div>
              <p className="text-gray-400 text-sm font-medium">Total Opportunities</p>
              <h3 className="text-3xl font-bold text-white mt-2">{data.total}</h3>
            </div>
            <div className="bg-blue-900/50 p-3 rounded-lg text-blue-400">
              <Activity size={24} />
            </div>
          </div>
        </div>

        <div className="bg-gray-900 border border-gray-800 p-6 rounded-2xl shadow-sm">
          <div className="flex justify-between items-start">
            <div>
              <p className="text-gray-400 text-sm font-medium">Approved</p>
              <h3 className="text-3xl font-bold text-green-400 mt-2">{data.approved}</h3>
            </div>
            <div className="bg-green-900/50 p-3 rounded-lg text-green-400">
              <CheckCircle size={24} />
            </div>
          </div>
        </div>

        <div className="bg-gray-900 border border-gray-800 p-6 rounded-2xl shadow-sm">
          <div className="flex justify-between items-start">
            <div>
              <p className="text-gray-400 text-sm font-medium">Pending Review</p>
              <h3 className="text-3xl font-bold text-orange-400 mt-2">{data.pending}</h3>
            </div>
            <div className="bg-orange-900/50 p-3 rounded-lg text-orange-400">
              <Clock size={24} />
            </div>
          </div>
        </div>

        <div className="bg-gray-900 border border-gray-800 p-6 rounded-2xl shadow-sm">
          <div className="flex justify-between items-start">
            <div>
              <p className="text-gray-400 text-sm font-medium">Avg Confidence</p>
              <h3 className="text-3xl font-bold text-purple-400 mt-2">{data.averageConfidence}%</h3>
            </div>
            <div className="bg-purple-900/50 p-3 rounded-lg text-purple-400">
              <TrendingUp size={24} />
            </div>
          </div>
        </div>
      </div>

      <div className="bg-gray-900 border border-gray-800 p-6 rounded-2xl shadow-sm mt-8">
        <h3 className="text-lg font-semibold text-white mb-6">Daily Opportunities</h3>
        <div className="h-80 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" vertical={false} />
              <XAxis dataKey="name" stroke="#9CA3AF" axisLine={false} tickLine={false} />
              <YAxis stroke="#9CA3AF" axisLine={false} tickLine={false} />
              <Tooltip 
                contentStyle={{ backgroundColor: '#1F2937', border: 'none', borderRadius: '8px', color: '#fff' }} 
                cursor={{ fill: '#374151', opacity: 0.4 }}
              />
              <Bar dataKey="opps" fill="#3B82F6" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </div>
  );
}
