import Container from '@mui/material/Container';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemButton from '@mui/material/ListItemButton';
import ListItemText from '@mui/material/ListItemText';
import Typography from '@mui/material/Typography';

const CheckpointSelection = () => {
  return (
    <Container>
      <Typography>Valitse rasti</Typography>
      <List>
        <ListItem disablePadding>
          <ListItemButton onClick={localStorage.setItem("checkpoint", 1)}>
            <ListItemText primary="1" />
          </ListItemButton>
        </ListItem>
        <ListItem disablePadding>
          <ListItemButton onClick={localStorage.setItem("checkpoint", 2)}>
            <ListItemText primary="2" />
          </ListItemButton>
        </ListItem>
      </List>
    </Container>
  )
}

export default CheckpointSelection