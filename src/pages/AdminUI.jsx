import * as React from 'react';
import PropTypes from 'prop-types';
import ThroughputTable from "../components/ThroughputTable"
import Typography from '@mui/material/Typography';
import Tabs from '@mui/material/Tabs';
import Tab from '@mui/material/Tab';
import Box from '@mui/material/Box';
import CheckpointTable from '../components/CheckpointTable';

const CustomTabPanel = (props) => {
  const { children, value, index, ...other } = props;

  return (
    <div
      role="tabpanel"
      hidden={value !== index}
      id={`simple-tabpanel-${index}`}
      aria-labelledby={`simple-tab-${index}`}
      {...other}
    >
      {value === index && <Box sx={{ p: 3 }}>{children}</Box>}
    </div>
  );
}

CustomTabPanel.propTypes = {
  children: PropTypes.node,
  index: PropTypes.number.isRequired,
  value: PropTypes.number.isRequired,
};

function a11yProps(index) {
  return {
    id: `simple-tab-${index}`,
    'aria-controls': `simple-tabpanel-${index}`,
  };
}


const AdminUI = () => {
  const [value, setValue] = React.useState(0);

  const handleChange = (event, newValue) => {
    setValue(newValue);
  };

  return (
     <Box sx={{ width: '100%' }}>
      <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
        <Tabs value={value} onChange={handleChange} aria-label="basic tabs example">
          <Tab label="Vartiot" {...a11yProps(0)} />
          <Tab label="Rastit" {...a11yProps(1)} />
          <Tab label="Rastien väliset matkat" {...a11yProps(2)} />
        </Tabs>
      </Box>
      <CustomTabPanel value={value} index={0}>
        <Typography variant='h2' gutterBottom component={'h1'}>
          Vartioiden eteneminen
        </Typography>
        <ThroughputTable />
      </CustomTabPanel>
      <CustomTabPanel value={value} index={1}>
        <Typography variant='h2' gutterBottom component={'h1'}>
          Rastien eteneminen
        </Typography>
        <CheckpointTable />
      </CustomTabPanel>
      <CustomTabPanel value={value} index={2}>
        Item Two
      </CustomTabPanel>
    </Box>
  )
}

export default AdminUI