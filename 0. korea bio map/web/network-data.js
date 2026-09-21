window.KOREA_BIO_MAP = {
  nodes: [
    { id:"P0001", name:"도준상", university:"Seoul National University", field:"면역항암", score:2, collaborator_count:2 },
    { id:"P0002", name:"서상우", university:"Seoul National University", field:"합성생물학", score:1, collaborator_count:1 },
    { id:"P0003", name:"서형석", university:"Seoul National University", field:"세포치료", score:0, collaborator_count:0 },
    { id:"P0004", name:"김원종", university:"POSTECH", field:"의료용 고분자", score:0, collaborator_count:0 },
    { id:"P0005", name:"김성은", university:"Kookmin University", field:"체외면역 평가", score:1, collaborator_count:1 }
  ],
  links: [
    { source:"P0001", target:"P0002", type:"collaboration", paper_count:1 },
    { source:"P0001", target:"P0005", type:"collaboration", paper_count:1 }
  ]
};
