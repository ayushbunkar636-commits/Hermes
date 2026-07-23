'use client';
import { useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, Filter, CheckCircle, XCircle, AlertTriangle, Info, Bell } from 'lucide-react';

export default function NotificationsPage() {
  const [notifications, setNotifications] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [filterType, setFilterType] = useState('all');

  useEffect(() => {
    fetch('/api/notifications?limit=100')
      .then(res => res.json())
      .then(d => {
        setNotifications(d.notifications || []);
        setLoading(false);
      });
  }, []);

  const getIcon = (type: string) => {
    switch (type) {
      case 'success':
      case 'approval':
      case 'telegram': return <CheckCircle className="text-green-400" size={20} />;
      case 'error': return <XCircle className="text-red-400" size={20} />;
      case 'warning': return <AlertTriangle className="text-orange-400" size={20} />;
      default: return <Info className="text-blue-400" size={20} />;
    }
  };

  const filtered = notifications.filter(n => {
    const matchesSearch = n.title.toLowerCase().includes(search.toLowerCase()) || n.message.toLowerCase().includes(search.toLowerCase());
    const matchesType = filterType === 'all' || n.type === filterType;
    return matchesSearch && matchesType;
  });

  const container = {
    hidden: { opacity: 0 },
    show: {
      opacity: 1,
      transition: {
        staggerChildren: 0.1
      }
    }
  };

  const item = {
    hidden: { opacity: 0, x: -20 },
    show: { opacity: 1, x: 0 }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      <div className="flex justify-between items-end">
        <div>
          <h1 className="text-3xl font-bold text-white mb-2 flex items-center gap-3">
            <Bell className="text-blue-500" size={28} />
            Notification Center
          </h1>
          <p className="text-gray-400">History of background events and alerts from Hermes Orchestrator.</p>
        </div>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-4 shadow-sm flex flex-col md:flex-row gap-4">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={18} />
          <input 
            type="text" 
            placeholder="Search events..." 
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full bg-gray-950 border border-gray-800 text-white pl-10 pr-4 py-2 rounded-xl focus:outline-none focus:border-blue-500 transition-colors"
          />
        </div>
        <select 
          value={filterType}
          onChange={e => setFilterType(e.target.value)}
          className="bg-gray-950 border border-gray-800 text-white px-4 py-2 rounded-xl focus:outline-none focus:border-blue-500 transition-colors"
        >
          <option value="all">All Types</option>
          <option value="approval">Approvals</option>
          <option value="error">Errors</option>
          <option value="telegram">Telegram</option>
          <option value="warning">Warnings</option>
        </select>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-2xl overflow-hidden min-h-[400px]">
        {loading ? (
          <div className="p-8 text-center text-gray-400">Loading history...</div>
        ) : filtered.length === 0 ? (
          <div className="p-12 text-center text-gray-500">
            <Bell size={48} className="mx-auto mb-4 opacity-20" />
            <p>No notifications match your filters.</p>
          </div>
        ) : (
          <motion.div 
            variants={container}
            initial="hidden"
            animate="show"
            className="divide-y divide-gray-800"
          >
            <AnimatePresence>
              {filtered.map(n => (
                <motion.div 
                  key={n.id}
                  variants={item}
                  className="p-4 hover:bg-gray-800/50 transition-colors flex gap-4 items-start"
                >
                  <div className="mt-1">
                    {getIcon(n.type)}
                  </div>
                  <div className="flex-1">
                    <div className="flex justify-between items-start mb-1">
                      <h4 className="font-semibold text-white">{n.title}</h4>
                      <span className="text-xs text-gray-500 whitespace-nowrap ml-4">
                        {new Date(n.created_at + 'Z').toLocaleString()}
                      </span>
                    </div>
                    <p className="text-sm text-gray-400">{n.message}</p>
                  </div>
                </motion.div>
              ))}
            </AnimatePresence>
          </motion.div>
        )}
      </div>
    </div>
  );
}
