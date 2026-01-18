import * as React from 'react';
import PropTypes from 'prop-types';
import Paper from '@mui/material/Paper';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TablePagination from '@mui/material/TablePagination';
import TableRow from '@mui/material/TableRow';
import { visuallyHidden } from '@mui/utils';
import Toolbar from '@mui/material/Toolbar';
import Tooltip from '@mui/material/Tooltip';
import FilterListIcon from '@mui/icons-material/FilterList';
import IconButton from '@mui/material/IconButton';
import TableSortLabel from '@mui/material/TableSortLabel';
import Box from '@mui/material/Box';
import InputLabel from '@mui/material/InputLabel';
import MenuItem from '@mui/material/MenuItem';
import FormControl from '@mui/material/FormControl';
import Select from '@mui/material/Select';
import Button from '@mui/material/Button';

const columns = [
  {
    id: 'rasti',
    label: 'Rasti',
    minWidth: 170,
  },
  {
    id: 'sarja',
    label: 'Sarja',
    minWidth: 170,
    align: 'right',
  },
  {
    id: 'suoritusaste',
    label: 'Suoritusaste',
    minWidth: 170,
    align: 'right',
  },
  {
    id: 'avg_suoritusaika',
    label: 'Keskimääräinen suoritusaika',
    minWidth: 170,
    align: 'right',
  }
];

const createData = (rasti, sarja, suorittaneetVartiot, kaikkiVartiot, suoritusaika) => {
  const suoritusaste = suorittaneetVartiot + ' / ' + kaikkiVartiot;
  return { rasti, sarja, suoritusaste, avg_suoritusaika: suoritusaika };
}

const descendingComparator = (a, b, orderBy) => {
  if (b[orderBy] < a[orderBy]) {
    return -1;
  }
  if (b[orderBy] > a[orderBy]) {
    return 1;
  }
  return 0;
}

const getComparator = (order, orderBy) => {
  return order === 'desc'
    ? (a, b) => descendingComparator(a, b, orderBy)
    : (a, b) => -descendingComparator(a, b, orderBy);
}

const rows = [
  createData(1, 'sininen', 2, 4, '2h'),
  createData(1, 'punainen', 1, 1, '1h'),
  createData(2, 'sininen', 0, 4, '-')
];

const EnhancedTableHead = (props) => {
  const {order, orderBy, onRequestSort} = props;
  const createSortHandler = (property) => (event) => {
    onRequestSort(event, property);
  };

  return (
    <TableHead>
      <TableRow>
        {columns.map((headCell) => (
          <TableCell
            key={headCell.id}
            align={headCell.numeric ? 'right' : 'left'}
            padding={headCell.disablePadding ? 'none' : 'normal'}
            sortDirection={orderBy === headCell.id ? order : false}
          >
            <TableSortLabel
              active={orderBy === headCell.id}
              direction={orderBy === headCell.id ? order : 'asc'}
              onClick={createSortHandler(headCell.id)}
            >
              {headCell.label}
              {orderBy === headCell.id ? (
                <Box component="span" sx={visuallyHidden}>
                  {order === 'desc' ? 'sorted descending' : 'sorted ascending'}
                </Box>
              ) : null}
            </TableSortLabel>
          </TableCell>
        ))}
      </TableRow>
    </TableHead>
  );
}

EnhancedTableHead.propTypes = {
  onRequestSort: PropTypes.func.isRequired,
  order: PropTypes.oneOf(['asc', 'desc']).isRequired,
  orderBy: PropTypes.string.isRequired,
};

const EnhancedTableToolbar = (props) => {
  const {
    onRequestFilterVisibility,
    isVisible,
    onSarjaFilterChange,
    sarjaFilter,
    onRastiFilterChange,
    rastiFilter,
    onClearFilters
  } = props;

  const changeFilterVisibility = () => onRequestFilterVisibility();

  const handleSarjaFilterChange = (event) => onSarjaFilterChange(event.target.value);

  const handleRastiFilterChange = (event) => onRastiFilterChange(event.target.value);

  const clearFilters = () => onClearFilters();

  return (
    <Toolbar
      sx={[
        {
          pl: { sm: 2 },
          pr: { xs: 1, sm: 1 },
        }
      ]}
    >
      <Tooltip title="Filter list">
        <IconButton onClick={changeFilterVisibility}>
          <FilterListIcon />
        </IconButton>
      </Tooltip>
      {isVisible &&
      <Box sx={{ display: "flex", gap: "10px", margin: "10px" }}>
        <FormControl sx={{ minWidth: 120 }} size="small">
          <InputLabel id="sarja-filter">Sarja</InputLabel>
          <Select
            labelId="sarja-filter"
            id="sarja-filter"
            value={sarjaFilter}
            label="Sarja"
            onChange={handleSarjaFilterChange}
          >
            <MenuItem value={''}>Kaikki sarjat</MenuItem>
            <MenuItem value={'sininen'}>Sininen</MenuItem>
            <MenuItem value={'punainen'}>Punainen</MenuItem>
            <MenuItem value={'ruskea'}>Ruskea</MenuItem>
            <MenuItem value={'harmaa'}>Harmaa</MenuItem>
            <MenuItem value={'keltainen'}>Keltainen</MenuItem>
          </Select>
          
        </FormControl>
        <FormControl sx={{ minWidth: 120 }} size="small">
          <InputLabel id="rasti-filter">Rasti</InputLabel>
          <Select
            labelId="rasti-filter"
            id="rasti-filter"
            value={rastiFilter}
            label="Rasti"
            onChange={handleRastiFilterChange}
          >
            <MenuItem value={0}>Kaikki rastit</MenuItem>
            <MenuItem value={1}>1</MenuItem>
            <MenuItem value={2}>2</MenuItem>
            <MenuItem value={3}>3</MenuItem>
          </Select>
        </FormControl>
        <Button variant="outlined" onClick={clearFilters}>Tyhjennä valinnat</Button>
      </Box>
      }
    </Toolbar>
  );
}

EnhancedTableToolbar.propTypes = {
  onRequestFilterVisibility: PropTypes.func.isRequired,
  isVisible: PropTypes.bool.isRequired,
  onSarjaFilterChange: PropTypes.func.isRequired,
  sarjaFilter: PropTypes.string.isRequired,
  onRastiFilterChange: PropTypes.func.isRequired,
  rastiFilter: PropTypes.number.isRequired,
  onClearFilters: PropTypes.func.isRequired
};

const CheckpointTable = () => {
  const [order, setOrder] = React.useState('asc');
  const [orderBy, setOrderBy] = React.useState('rasti');
  const [page, setPage] = React.useState(0);
  const [rowsPerPage, setRowsPerPage] = React.useState(10);
  const [filtersVisible, setFiltersVisible] = React.useState(false);
  const [sarjaFilter, setSarjaFilter] = React.useState('');
  const [rastiFilter, setRastiFilter] = React.useState(0);

  const handleRequestSort = (event, property) => {
    const isAsc = orderBy === property && order === 'asc';
    setOrder(isAsc ? 'desc' : 'asc');
    setOrderBy(property);
  };

  const handleChangePage = (event, newPage) => {
    setPage(newPage);
  };

  const handleChangeRowsPerPage = (event) => {
    setRowsPerPage(+event.target.value);
    setPage(0);
  };

  const handleFilterVisibility = () => {
    setFiltersVisible(!filtersVisible);
  };

  const handleSarjaFilterChange = (newFilter) => {
    setSarjaFilter(newFilter);
  }

  const handleRastiFilterChange = (newFilter) => {
    setRastiFilter(newFilter);
  }

  const clearFilters = () => {
    setSarjaFilter('');
    setRastiFilter(0);
  }

  const visibleRows = React.useMemo(
    () =>
      [...rows]
        .sort(getComparator(order, orderBy))
        .slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage),
    [order, orderBy, page, rowsPerPage],
  );

  return (
    <Paper sx={{ width: '100%', overflow: 'hidden' }}>
      <EnhancedTableToolbar
        onRequestFilterVisibility={handleFilterVisibility}
        isVisible={filtersVisible}
        onSarjaFilterChange={handleSarjaFilterChange}
        sarjaFilter={sarjaFilter}
        onRastiFilterChange={handleRastiFilterChange}
        rastiFilter={rastiFilter}
        onClearFilters={clearFilters}
      />
      <TableContainer sx={{ maxHeight: 440 }}>
        <Table stickyHeader aria-label="sticky table">
          <EnhancedTableHead
              order={order}
              orderBy={orderBy}
              onRequestSort={handleRequestSort}
            />
          <TableBody>
            {visibleRows
              .slice(page * rowsPerPage, page * rowsPerPage + rowsPerPage)
              .filter((row) =>
                row.sarja.includes(sarjaFilter) &&
                (rastiFilter === 0 ? true : row.rasti === rastiFilter)
              )
              .map((row) => {
                return (
                  <TableRow hover role="checkbox" tabIndex={-1} key={row.code}>
                    {columns.map((column) => {
                      const value = row[column.id];
                      return (
                        <TableCell key={column.id} align={column.align}>
                          {column.format
                            ? column.format(value)
                            : value}
                        </TableCell>
                      );
                    })}
                  </TableRow>
                );
              })}
          </TableBody>
        </Table>
      </TableContainer>
      <TablePagination
        rowsPerPageOptions={[10, 25, 100]}
        component="div"
        count={rows.length}
        rowsPerPage={rowsPerPage}
        page={page}
        onPageChange={handleChangePage}
        onRowsPerPageChange={handleChangeRowsPerPage}
      />
    </Paper>
  );
}

export default CheckpointTable
