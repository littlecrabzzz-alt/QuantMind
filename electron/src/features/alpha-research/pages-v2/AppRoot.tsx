import React from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import ResearchWorkbench from './ResearchWorkbench';
import { MiningDashboardPage } from '../pages-v2/MiningDashboardPage';
import { FactorLibraryPage } from '../pages-v2/FactorLibraryPage';
import { BacktestPage } from '../pages-v2/BacktestPage';
import { SettingsPage } from '../pages-v2/SettingsPage';
import { Layout } from '../components-v2/layout/Layout';
import type { PageId } from '../components-v2/layout/Layout';
import { ParticleBackground } from '../components-v2/ParticleBackground';
import { TaskProvider } from '../context-v2/TaskContext';

// Inner component to access context
const AppContent: React.FC = () => {
  const location = useLocation(), navigate = useNavigate();
  const requested = new URLSearchParams(location.search).get('page');
  const currentPage: PageId = ['library', 'backtest', 'mining_dashboard', 'settings'].includes(requested || '') ? requested as PageId : 'home';
  const setCurrentPage = (page: PageId) => {
    const params = new URLSearchParams(location.search);
    params.set('page', page); params.delete('factor');
    navigate({ pathname: location.pathname, search: params.toString() });
  };

  return (
    <>
      <ParticleBackground />
      {/* Conditional rendering: only mount the active page, unmount others when switching.
          TaskProvider persists mining/backtest state across page switches. */}
      {currentPage === 'home' && <ResearchWorkbench onNavigate={setCurrentPage} />}
      {currentPage === 'mining_dashboard' && <MiningDashboardPage onNavigate={setCurrentPage} />}
      {currentPage === 'library' && (
        <Layout currentPage={currentPage} onNavigate={setCurrentPage}>
          <FactorLibraryPage onNavigate={setCurrentPage} />
        </Layout>
      )}
      {currentPage === 'backtest' && (
        <Layout currentPage={currentPage} onNavigate={setCurrentPage}>
          <BacktestPage />
        </Layout>
      )}
      {currentPage === 'settings' && (
        <Layout currentPage={currentPage} onNavigate={setCurrentPage}>
          <SettingsPage />
        </Layout>
      )}
    </>
  );
};

const AppRoot: React.FC = () => {
  return (
    <TaskProvider>
      <AppContent />
    </TaskProvider>
  );
};

export default AppRoot;
export { AppRoot as App };
