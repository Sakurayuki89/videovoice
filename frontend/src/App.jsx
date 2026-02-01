import { BrowserRouter, Routes, Route } from 'react-router-dom';
import Layout from './components/Layout';
import Home from './pages/Home';
import Process from './pages/Process';
import Result from './pages/Result';
import { VideoProvider } from './contexts/VideoContext';
import './App.css';

function App() {
  return (
    <BrowserRouter>
      <VideoProvider>
        <Layout>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/process/:jobId" element={<Process />} />
            <Route path="/result/:jobId" element={<Result />} />
          </Routes>
        </Layout>
      </VideoProvider>
    </BrowserRouter>
  );
}

export default App;
