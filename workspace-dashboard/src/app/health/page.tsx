'use client';
import { useEffect, useState } from 'react';
import { Server, Database, Brain, Bot, Cpu, MemoryStick, HardDrive, Activity } from 'lucide-react';
import { motion } from 'framer-motion';

export default function HealthPage() {
  const [health, setHealth] = useState<any>(null);

  useEffect(() => {
    const fetchHealth = () => fetch('/api/health').then(res => res.json()).then(setHealth);
    fetchHealth();
    const interval = setInterval(fetchHealth, 10000);
    return () => clearInterval(interval);
  }, []);

  const StatusLight = ({ status }: { status: string }) => {
    const colors: Record<string, string> = {
      green: 'bg-green-500 shadow-[0_0_10px_rgba(34,197,94,0.5)]',
      yellow: 'bg-yellow-500 shadow-[0_0_10px_rgba(234,179,8,0.5)]',
      red: 'bg-red-500 shadow-[0_0_10px_rgba(239,68,68,0.5)]',
    };
    return <div className={`w-3 h-3 rounded-full ${colors[status] || 'bg-gray-500'}`} />;
  };

  const container = { hidden: { opacity: 0 }, show: { opacity: 1, transition: { staggerChildren: 0.1 } } };
  const item = { hidden: { opacity: 0, y: 20 }, show: { opacity: 1, y: 0 } };

  if (!health) return <div className="text-gray-400 text-center py-20">Fetching system metrics...</div>;
  if (health.error) return <div className="text-red-400 text-center py-20">Error: {health.error}</div>;

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      <div>
        <h1 className="text-3xl font-bold text-white mb-2 flex items-center gap-3">
          <Activity className="text-blue-500" size={28} />
          System Health
        </h1>
        <p className="text-gray-400">Real-time infrastructure monitoring for Hermes Orchestrator.</p>
      </div>

      <motion.div variants={container} initial="hidden" animate="show" className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        
        <motion.div variants={item} className="bg-gray-900 border border-gray-800 rounded-2xl p-6 flex flex-col justify-between hover:border-gray-700 transition-colors">
          <div className="flex justify-between items-start mb-4">
            <div className="bg-gray-800 p-3 rounded-xl text-blue-400"><Database size={24} /></div>
            <StatusLight status={health.database.status} />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-white">Postgres Database</h3>
            <p className="text-gray-400 text-sm mt-1">Latency: {health.database.latency}ms</p>
          </div>
        </motion.div>

        <motion.div variants={item} className="bg-gray-900 border border-gray-800 rounded-2xl p-6 flex flex-col justify-between hover:border-gray-700 transition-colors">
          <div className="flex justify-between items-start mb-4">
            <div className="bg-gray-800 p-3 rounded-xl text-purple-400"><Server size={24} /></div>
            <StatusLight status={health.scheduler.status} />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-white">Python Scheduler</h3>
            <p className="text-gray-400 text-sm mt-1 truncate">Last Beat: {health.scheduler.lastHeartbeat}</p>
          </div>
        </motion.div>

        <motion.div variants={item} className="bg-gray-900 border border-gray-800 rounded-2xl p-6 flex flex-col justify-between hover:border-gray-700 transition-colors">
          <div className="flex justify-between items-start mb-4">
            <div className="bg-gray-800 p-3 rounded-xl text-orange-400"><Brain size={24} /></div>
            <StatusLight status={health.ai.status} />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-white">AI Inference (Qwen 3)</h3>
            <p className="text-gray-400 text-sm mt-1">Status: {health.ai.message}</p>
          </div>
        </motion.div>

        <motion.div variants={item} className="bg-gray-900 border border-gray-800 rounded-2xl p-6 flex flex-col justify-between hover:border-gray-700 transition-colors">
          <div className="flex justify-between items-start mb-4">
            <div className="bg-gray-800 p-3 rounded-xl text-sky-400"><Bot size={24} /></div>
            <StatusLight status={health.telegram.status} />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-white">Telegram Gateway</h3>
            <p className="text-gray-400 text-sm mt-1">Connected & Ready</p>
          </div>
        </motion.div>

        <motion.div variants={item} className="bg-gray-900 border border-gray-800 rounded-2xl p-6 flex flex-col justify-between hover:border-gray-700 transition-colors">
          <div className="flex justify-between items-start mb-4">
            <div className="bg-gray-800 p-3 rounded-xl text-pink-400"><Cpu size={24} /></div>
            <StatusLight status="green" />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-white">Dashboard CPU</h3>
            <p className="text-gray-400 text-sm mt-1">Load: {health.system.cpu.toFixed(2)}</p>
          </div>
        </motion.div>

        <motion.div variants={item} className="bg-gray-900 border border-gray-800 rounded-2xl p-6 flex flex-col justify-between hover:border-gray-700 transition-colors">
          <div className="flex justify-between items-start mb-4">
            <div className="bg-gray-800 p-3 rounded-xl text-green-400"><MemoryStick size={24} /></div>
            <StatusLight status={health.system.memory > 0.9 ? 'red' : 'green'} />
          </div>
          <div>
            <h3 className="text-lg font-semibold text-white">Dashboard Memory</h3>
            <p className="text-gray-400 text-sm mt-1">Utilized: {(health.system.memory * 100).toFixed(1)}%</p>
          </div>
        </motion.div>

      </motion.div>
    </div>
  );
}
