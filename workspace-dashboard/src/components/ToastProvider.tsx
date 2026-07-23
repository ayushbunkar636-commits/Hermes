'use client';
import { createContext, useContext, useState, useCallback, ReactNode, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { CheckCircle, XCircle, AlertTriangle, Info, X } from 'lucide-react';

export type ToastType = 'success' | 'error' | 'warning' | 'info';

interface Toast {
  id: string;
  type: ToastType;
  title: string;
  message: string;
}

interface ToastContextType {
  toast: (type: ToastType, title: string, message: string) => void;
}

const ToastContext = createContext<ToastContextType | undefined>(undefined);

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const toast = useCallback((type: ToastType, title: string, message: string) => {
    const id = Math.random().toString(36).substring(2, 9);
    setToasts((prev) => [...prev, { id, type, title, message }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 5000);
  }, []);

  // Poll DB for new unread notifications and show them as toast
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch('/api/notifications?limit=5');
        const data = await res.json();
        if (data.notifications) {
          const unread = data.notifications.filter((n: any) => n.is_read === 0);
          for (const n of unread) {
            let ttype: ToastType = 'info';
            if (n.type === 'error') ttype = 'error';
            if (n.type === 'approval' || n.type === 'success' || n.type === 'telegram') ttype = 'success';
            if (n.type === 'warning') ttype = 'warning';
            
            toast(ttype, n.title, n.message);
            await fetch('/api/notifications', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ action: 'mark_read', id: n.id })
            });
          }
        }
      } catch (e) {}
    }, 10000); // Check every 10 seconds
    return () => clearInterval(interval);
  }, [toast]);

  const removeToast = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  const getIcon = (type: ToastType) => {
    switch (type) {
      case 'success': return <CheckCircle className="text-green-400" size={24} />;
      case 'error': return <XCircle className="text-red-400" size={24} />;
      case 'warning': return <AlertTriangle className="text-orange-400" size={24} />;
      default: return <Info className="text-blue-400" size={24} />;
    }
  };

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm w-full pointer-events-none">
        <AnimatePresence>
          {toasts.map((t) => (
            <motion.div
              key={t.id}
              initial={{ opacity: 0, y: 50, scale: 0.9 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, scale: 0.9, transition: { duration: 0.2 } }}
              className="pointer-events-auto bg-gray-900 border border-gray-800 rounded-xl shadow-2xl overflow-hidden flex"
            >
              <div className="p-4 flex gap-3 w-full items-start">
                {getIcon(t.type)}
                <div className="flex-1 pt-0.5">
                  <h4 className="text-sm font-semibold text-white">{t.title}</h4>
                  <p className="text-sm text-gray-400 mt-1 leading-relaxed">{t.message}</p>
                </div>
                <button 
                  onClick={() => removeToast(t.id)}
                  className="text-gray-500 hover:text-white transition-colors p-1"
                >
                  <X size={16} />
                </button>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}
