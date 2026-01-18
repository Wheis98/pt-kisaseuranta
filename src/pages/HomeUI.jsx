import { NavLink } from "react-router";
import Container from '@mui/material/Container';

const HomeUI = () => {
  return (
    <Container>
      <p>Welcome home!</p>
      <NavLink to="/reader">Avaa lukija</NavLink>
    </Container>
  )
}

export default HomeUI