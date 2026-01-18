import Container from '@mui/material/Container';
import Reader from '../components/Reader';
import CheckpointSelection from '../components/CheckpointSelection';
import { useState } from 'react';

const ReaderUI = () => {
  const [onCheckpoint, setOnCheckpoint] = useState([])

  const checkpoint = localStorage.getItem("checkpoint")

  return (
    <Container>
      {
        checkpoint ? <Reader /> : <CheckpointSelection />
      }
    </Container>
  )
}

export default ReaderUI