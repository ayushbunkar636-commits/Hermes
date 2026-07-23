'use client';
import { useEffect, useState } from 'react';
import { Globe, Plus, AlertCircle, Link as LinkIcon, Tag, Search, Terminal, Trash2, Map } from 'lucide-react';
import { motion, AnimatePresence } from 'framer-motion';
import { useToast } from '@/components/ToastProvider';

export default function ProjectsPage() {
  const [projects, setProjects] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [url, setUrl] = useState('');
  const [niche, setNiche] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [adding, setAdding] = useState(false);
  const [activeProject, setActiveProject] = useState<number | null>(null);
  const [sourceDomain, setSourceDomain] = useState('');
  const [addingSource, setAddingSource] = useState(false);
  const [activityLogs, setActivityLogs] = useState<any[]>([]);
  const [projectToDelete, setProjectToDelete] = useState<number | null>(null);
  const [scanningProject, setScanningProject] = useState<number | null>(null);
  const { toast } = useToast();

  const fetchActivity = async () => {
    try {
      const res = await fetch('/api/activity');
      const data = await res.json();
      setActivityLogs(data.events || []);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    fetchActivity();
    const interval = setInterval(fetchActivity, 2000);
    return () => clearInterval(interval);
  }, []);

  const fetchProjects = async () => {
    try {
      const res = await fetch('/api/projects', { cache: 'no-store' });
      const data = await res.json();
      setProjects(data.data || []);
      setLoading(false);
    } catch (e) {
      console.error(e);
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchProjects();
  }, []);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url || !niche) return;
    
    setAdding(true);
    setMessage('');
    setError('');

    try {
      const res = await fetch('/api/projects', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, niche })
      });
      const data = await res.json();

      if (res.ok) {
        toast('success', 'Project Added', 'The orchestrator will begin scanning shortly.');
        setUrl('');
        setNiche('');
        fetchProjects(); // refresh list
      } else {
        toast('error', 'Failed to add project', data.error || 'Unknown error');
      }
    } catch (e: any) {
      toast('error', 'Error', e.message);
    }
    setAdding(false);
  };

  const handleAddSource = async (e: React.FormEvent, projectId: number) => {
    e.preventDefault();
    if (!sourceDomain) return;
    
    setAddingSource(true);
    try {
      const res = await fetch(`/api/projects/${projectId}/sources`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ domain: sourceDomain, site_type: 'forum' })
      });
      if (res.ok) {
        toast('success', 'Source Added', `Added ${sourceDomain} to whitelist.`);
        setSourceDomain('');
        setActiveProject(null);
        fetchProjects();
      } else {
        toast('error', 'Failed', 'Failed to add source');
      }
    } catch (err: any) {
      toast('error', 'Error', err.message);
    }
    setAddingSource(false);
  };

  const executeDelete = async (id: number) => {
    // Optimistically remove from UI immediately
    setProjects(prev => prev.filter(p => p.id !== id));
    setProjectToDelete(null);

    try {
      const res = await fetch(`/api/projects/${id}`, { method: 'DELETE' });
      if (res.ok) {
        toast('success', 'Deleted', 'Project deleted successfully.');
      } else {
        const data = await res.json();
        toast('error', 'Delete Failed', data.error || 'Failed to delete project');
        // Restore list if delete failed
        fetchProjects();
      }
    } catch (e: any) {
      toast('error', 'Error', e.message);
      // Restore list on network error
      fetchProjects();
    }
  };

  const handleDeleteClick = (id: number) => {
    setProjectToDelete(id);
  };

  const handleScanSitemap = async (id: number, url: string) => {
    setScanningProject(id);
    try {
      const res = await fetch(`/api/projects/${id}/scan-sitemap`, { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        toast('success', 'Sitemap Scan Started', `Scanning ${url} for pages in the background.`);
      } else {
        toast('error', 'Scan Failed', data.error || 'Could not start sitemap scan.');
      }
    } catch (e: any) {
      toast('error', 'Error', e.message);
    }
    setScanningProject(null);
  };

  const container = { hidden: { opacity: 0 }, show: { opacity: 1, transition: { staggerChildren: 0.1 } } };
  const item = { hidden: { opacity: 0, y: 20 }, show: { opacity: 1, y: 0 } };

  return (
    <div className="max-w-5xl mx-auto space-y-8 relative">
      {/* Delete Confirmation Modal */}
      <AnimatePresence>
        {projectToDelete && (
          <motion.div 
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4"
          >
            <motion.div 
              initial={{ scale: 0.95, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }}
              className="bg-gray-900 border border-gray-800 rounded-2xl p-6 max-w-md w-full shadow-2xl"
            >
              <h3 className="text-xl font-semibold text-white mb-2">Delete Project?</h3>
              <p className="text-gray-400 mb-6 text-sm leading-relaxed">
                Are you sure you want to delete this project? This action cannot be undone and will remove all associated whitelist sources and analytics data.
              </p>
              <div className="flex justify-end gap-3">
                <button 
                  onClick={() => setProjectToDelete(null)} 
                  className="px-4 py-2 text-sm font-medium text-gray-300 hover:text-white bg-gray-800 hover:bg-gray-700 rounded-xl transition-colors"
                >
                  Cancel
                </button>
                <button 
                  onClick={() => executeDelete(projectToDelete)} 
                  className="px-4 py-2 text-sm font-medium bg-red-600 hover:bg-red-700 text-white rounded-xl transition-colors shadow-lg shadow-red-900/20"
                >
                  Yes, Delete Project
                </button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      <div>
        <h1 className="text-3xl font-bold text-white mb-2 flex items-center gap-3">
          <Globe className="text-blue-500" size={28} />
          Projects Management
        </h1>
        <p className="text-gray-400">Add websites for Hermes to scan and discover backlink opportunities.</p>
      </div>

      <div className="bg-gray-950/50 border border-gray-800 rounded-2xl p-4 shadow-sm overflow-hidden relative">
        <h2 className="text-sm font-semibold text-blue-400 mb-2 flex items-center gap-2">
          <Terminal size={16} /> Live System Activity
        </h2>
        <div className="space-y-1 h-32 overflow-y-auto font-mono text-xs text-gray-300 flex flex-col-reverse">
          <AnimatePresence>
            {activityLogs.map((log, i) => (
              <motion.div 
                key={log.timestamp + i}
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: 1, x: 0 }}
                className="py-1 border-b border-gray-800/50 last:border-0"
              >
                <span className="text-gray-500 mr-2">[{log.timestamp}]</span>
                <span className={log.message.includes('found') ? 'text-green-400' : 'text-gray-300'}>{log.message}</span>
              </motion.div>
            ))}
            {activityLogs.length === 0 && (
              <div className="text-gray-500 italic">Waiting for backend activity...</div>
            )}
          </AnimatePresence>
        </div>
        <div className="absolute top-4 right-4 flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
          </span>
          <span className="text-xs text-gray-500 uppercase tracking-wider font-semibold">Live</span>
        </div>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-2xl p-6 shadow-sm">
        <h2 className="text-xl font-semibold text-white mb-6">Track New Project</h2>

        <form onSubmit={handleAdd} className="flex flex-col md:flex-row gap-4">
          <div className="flex-1 relative">
            <LinkIcon className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" size={18} />
            <input 
              type="url"
              required
              placeholder="https://yourwebsite.com"
              value={url}
              onChange={e => setUrl(e.target.value)}
              className="w-full bg-gray-950 border border-gray-800 text-white pl-10 pr-4 py-3 rounded-xl focus:outline-none focus:border-blue-500 transition-colors"
            />
          </div>
          <div className="flex-1 relative">
            <Tag className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500" size={18} />
            <input 
              type="text"
              required
              placeholder="Project Niche (e.g. AI Tools, SaaS)"
              value={niche}
              onChange={e => setNiche(e.target.value)}
              className="w-full bg-gray-950 border border-gray-800 text-white pl-10 pr-4 py-3 rounded-xl focus:outline-none focus:border-blue-500 transition-colors"
            />
          </div>
          <button 
            type="submit" 
            disabled={adding}
            className="bg-blue-600 hover:bg-blue-700 disabled:bg-blue-800 text-white px-6 py-3 rounded-xl font-medium flex items-center justify-center gap-2 transition-colors min-w-[140px]"
          >
            {adding ? 'Adding...' : <><Plus size={20} /> Add Project</>}
          </button>
        </form>
      </div>

      <div>
        <h2 className="text-xl font-semibold text-white mb-4">Active Projects</h2>
        
        <div className="bg-gray-900 border border-gray-800 rounded-2xl overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm text-gray-400">
              <thead className="bg-gray-950/50 text-gray-300 uppercase font-medium">
                <tr>
                  <th className="px-6 py-4">URL</th>
                  <th className="px-6 py-4">Niche</th>
                  <th className="px-6 py-4">Status</th>
                  <th className="px-6 py-4 text-right">Added On</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan={4} className="text-center py-8">Loading projects...</td></tr>
                ) : projects.length === 0 ? (
                  <tr><td colSpan={4} className="text-center py-8 text-gray-500">No projects found. Add one above!</td></tr>
                ) : (
                  projects.map((proj) => {
                    const config = proj.config_json || {};
                    const queries = config.recent_queries || [];
                    
                    return (
                      <tr key={proj.id} className="border-b border-gray-800 hover:bg-gray-800/50 transition-colors">
                        <td className="px-6 py-4">
                          <div className="flex items-start justify-between gap-2">
                            <span className="font-medium text-white block break-all">{proj.project_url}</span>
                            <div className="flex items-center gap-1 flex-shrink-0">
                              <button
                                onClick={() => handleScanSitemap(proj.id, proj.project_url)}
                                title="Scan Sitemap"
                                disabled={scanningProject === proj.id}
                                className="text-emerald-400 hover:text-emerald-300 hover:bg-emerald-900/30 p-1.5 rounded-lg transition-colors disabled:opacity-50"
                              >
                                <Map size={16} />
                              </button>
                              <button 
                                onClick={() => handleDeleteClick(proj.id)} 
                                title="Delete Project"
                                className="text-red-400 hover:text-red-300 hover:bg-red-900/30 p-1.5 rounded-lg transition-colors"
                              >
                                <Trash2 size={16} />
                              </button>
                            </div>
                          </div>
                          
                          {/* Sources UI */}
                          <div className="mt-4 pt-3 border-t border-gray-800">
                            <div className="flex items-center justify-between mb-2">
                              <span className="text-xs font-semibold text-gray-400 uppercase tracking-wider">Data Sources (Whitelist)</span>
                              <button 
                                onClick={() => setActiveProject(activeProject === proj.id ? null : proj.id)}
                                className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
                              >
                                <Plus size={12} /> Add Source
                              </button>
                            </div>
                            
                            <div className="flex flex-wrap gap-2">
                              {proj.sources?.length > 0 ? (
                                proj.sources.map((src: any) => (
                                  <span key={src.id} className="bg-gray-800/50 text-gray-300 text-xs px-2 py-1 rounded border border-gray-700/50">
                                    {src.domain}
                                  </span>
                                ))
                              ) : (
                                <span className="text-xs text-gray-600 italic">No sources added yet.</span>
                              )}
                            </div>
                            
                            {activeProject === proj.id && (
                              <div className="mt-3">
                                <div className="flex gap-2 mb-2">
                                  <span className="text-xs text-gray-500 flex items-center">Quick Add:</span>
                                  <button onClick={() => setSourceDomain('reddit.com/r/SaaS')} className="text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 px-2 py-0.5 rounded transition-colors">Reddit /r/SaaS</button>
                                  <button onClick={() => setSourceDomain('news.ycombinator.com')} className="text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 px-2 py-0.5 rounded transition-colors">HackerNews</button>
                                  <button onClick={() => setSourceDomain('indiehackers.com')} className="text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 px-2 py-0.5 rounded transition-colors">IndieHackers</button>
                                </div>
                                <form onSubmit={(e) => handleAddSource(e, proj.id)} className="flex gap-2">
                                  <input 
                                    type="text" 
                                    placeholder="e.g. reddit.com/r/SaaS" 
                                    value={sourceDomain}
                                    onChange={(e) => setSourceDomain(e.target.value)}
                                    className="flex-1 bg-gray-950 border border-gray-700 text-white text-sm px-3 py-1.5 rounded-lg focus:outline-none focus:border-blue-500"
                                    required
                                  />
                                  <button 
                                    type="submit" 
                                    disabled={addingSource}
                                    className="bg-blue-600 hover:bg-blue-700 text-white text-sm px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
                                  >
                                    {addingSource ? 'Adding...' : 'Save'}
                                  </button>
                                </form>
                              </div>
                            )}
                          </div>
                        </td>
                        <td className="px-6 py-4 align-top">
                          <span className="bg-gray-800 px-3 py-1 rounded-full text-xs text-blue-400 border border-gray-700 inline-block mt-1">
                            {proj.niche}
                          </span>
                        </td>
                        <td className="px-6 py-4 align-top">
                          <span className="text-green-400 text-xs flex items-center gap-1 mt-2">
                            <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse"></span>
                            Active
                          </span>
                        </td>
                        <td className="px-6 py-4 text-right align-top">
                          <span className="inline-block mt-2">{new Date(proj.created_at).toLocaleDateString()}</span>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
